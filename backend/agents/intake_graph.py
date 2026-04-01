"""
Onsera Health — Patient Intake LangGraph Pipeline

Six-node agentic pipeline:
  transcribe → extract_signals → meal_analysis → risk_flag
      → [human_review_gate ⚡NodeInterrupt] → generate_summary → END

Clinical AI design principles applied here:
  1. Safety decisions (risk_flag) are ALWAYS deterministic Python — never LLM.
  2. Structured output via Pydantic + with_structured_output() removes brittle JSON
     string parsing; schema validation is enforced by the model layer.
  3. Extraction failure ESCALATES to HIGH risk — never silently downgrades.
  4. NodeInterrupt + MemorySaver checkpointer enables true human-in-the-loop:
     graph state is persisted; the clinician's approval resumes the exact
     execution from where it paused without re-running earlier nodes.
  5. Every node records its latency by returning a new merged dict (immutable
     state pattern) rather than mutating the existing dict in place.
"""

import logging
import os
import time
from enum import Enum
from typing import Annotated, Any, Optional

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import NodeInterrupt
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

load_dotenv()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Risk level enum
# ---------------------------------------------------------------------------

class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Pydantic schemas — used for with_structured_output() and API serialisation
# ---------------------------------------------------------------------------

class MedicationRecord(BaseModel):
    name: str
    dose: str = ""
    adherent: bool = True


class ClinicalSignals(BaseModel):
    """Structured clinical signals extracted from the patient transcript."""
    symptoms: list[str] = Field(default_factory=list, description="Symptoms mentioned by the patient")
    medications: list[MedicationRecord] = Field(default_factory=list, description="Medications with dose and adherence")
    meals_mentioned: list[str] = Field(default_factory=list, description="Foods and meals described")
    weight_change: Optional[str] = Field(None, description="'gain', 'loss', 'stable', or null")
    exercise_reported: bool = Field(False, description="Whether any exercise was mentioned")
    mood: Optional[str] = Field(None, description="Patient's reported mood, or null")
    sleep_hours: Optional[float] = Field(None, description="Hours of sleep reported, or null")
    concerns: list[str] = Field(default_factory=list, description="Patient concerns or questions")
    missed_doses: bool = Field(False, description="True if any medication doses were missed")


class MealAnalysis(BaseModel):
    """Nutritional analysis of the meals described by the patient."""
    estimated_calories: Optional[int] = Field(None, description="Approximate total daily calories")
    carb_load: str = Field("moderate", description="'low', 'moderate', or 'high'")
    saturated_fat_concern: bool = Field(False, description="True if saturated fat intake is clinically concerning")
    glycemic_concern: bool = Field(False, description="True if glycemic load is concerning for a diabetic patient")
    meal_quality_score: int = Field(5, ge=1, le=10, description="Overall meal quality: 1=very poor, 10=excellent")
    flags: list[str] = Field(default_factory=list, description="Specific dietary flags or warnings")
    notes: str = Field("", description="Brief clinical note on nutritional findings")


# ---------------------------------------------------------------------------
# Agent state
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    audio_path: str
    patient_id: str
    transcript: str
    clinical_signals: dict
    meal_data: dict
    risk_level: RiskLevel
    risk_reasons: list
    clinical_summary: str
    requires_human_review: bool
    human_review_note: str
    extraction_failed: bool          # True if extract_signals structured output failed
    latency_ms: dict
    messages: Annotated[list[BaseMessage], add_messages]


# ---------------------------------------------------------------------------
# Client singletons — lazy-initialised so module imports work without keys
# ---------------------------------------------------------------------------

_groq_client = None
_llm_fast: ChatAnthropic | None = None
_llm: ChatAnthropic | None = None


def _get_groq():
    """Groq client singleton — avoids creating a new HTTP client per call."""
    global _groq_client
    if _groq_client is None:
        from groq import Groq
        _groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    return _groq_client


def _get_llm_fast() -> ChatAnthropic:
    """Low-temperature Claude for structured extraction (temperature=0)."""
    global _llm_fast
    if _llm_fast is None:
        _llm_fast = ChatAnthropic(
            model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5"),
            temperature=0,
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        )
    return _llm_fast


def _get_llm() -> ChatAnthropic:
    """Full-quality Claude for narrative summary generation (temperature=0.3)."""
    global _llm
    if _llm is None:
        _llm = ChatAnthropic(
            model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5"),
            temperature=0.3,
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        )
    return _llm


# ---------------------------------------------------------------------------
# Node 1 — transcribe
# ---------------------------------------------------------------------------

def transcribe(state: AgentState) -> dict:
    """
    Transcribe audio using Groq Whisper (whisper-large-v3).
    Uses the module-level Groq singleton — not recreated per call.
    """
    t0 = time.monotonic()
    audio_path = state["audio_path"]

    with open(audio_path, "rb") as audio_file:
        transcription = _get_groq().audio.transcriptions.create(
            model="whisper-large-v3",
            file=audio_file,
            response_format="text",
        )

    transcript = transcription if isinstance(transcription, str) else transcription.text
    elapsed = round((time.monotonic() - t0) * 1000, 2)

    logger.info("transcribe: %.0f ms | %d chars", elapsed, len(transcript))
    return {
        "transcript": transcript,
        "latency_ms": {**state.get("latency_ms", {}), "transcribe": elapsed},
    }


# ---------------------------------------------------------------------------
# Node 2 — extract_signals
# ---------------------------------------------------------------------------

_EXTRACT_SYSTEM = (
    "You are a clinical NLP assistant. Extract structured clinical signals "
    "from the patient transcript. Be precise and conservative — only extract "
    "information explicitly stated. Set missed_doses=true only if the patient "
    "explicitly mentions forgetting or skipping medication."
)


def extract_signals(state: AgentState) -> dict:
    """
    Extract structured clinical signals using with_structured_output(ClinicalSignals).

    Uses Anthropic tool-calling under the hood — schema-enforced, no manual
    JSON parsing. On failure, sets extraction_failed=True which risk_flag
    will treat as HIGH risk (escalate, never silently downgrade).
    """
    t0 = time.monotonic()
    transcript = state.get("transcript", "")

    structured_llm = _get_llm_fast().with_structured_output(ClinicalSignals)

    try:
        result: ClinicalSignals = structured_llm.invoke([
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user", "content": f"Patient transcript:\n{transcript}"},
        ])
        signals = result.model_dump()
        # Flatten nested MedicationRecord objects → plain dicts
        signals["medications"] = [
            m if isinstance(m, dict) else m.model_dump()
            for m in result.medications
        ]
        extraction_failed = False
        logger.info("extract_signals: success | missed_doses=%s symptoms=%d",
                    signals.get("missed_doses"), len(signals.get("symptoms", [])))
    except Exception as exc:
        # Schema validation or API failure — ESCALATE, do not silently downgrade
        logger.error("extract_signals FAILED — will escalate to HIGH risk: %s", exc)
        signals = {
            "symptoms": [], "medications": [], "meals_mentioned": [],
            "weight_change": None, "exercise_reported": False,
            "mood": None, "sleep_hours": None, "concerns": [],
            "missed_doses": False,
        }
        extraction_failed = True

    elapsed = round((time.monotonic() - t0) * 1000, 2)
    logger.info("extract_signals: %.0f ms", elapsed)
    return {
        "clinical_signals": signals,
        "extraction_failed": extraction_failed,
        "latency_ms": {**state.get("latency_ms", {}), "extract_signals": elapsed},
    }


# ---------------------------------------------------------------------------
# Node 3 — meal_analysis
# ---------------------------------------------------------------------------

_MEAL_SYSTEM = (
    "You are a clinical dietitian assistant. Analyse the nutritional content "
    "of the meals described by a patient. Focus on clinical relevance: "
    "glycemic load for diabetic patients, saturated fat for cardiac patients, "
    "and overall meal quality. Be specific and concise."
)


def meal_analysis(state: AgentState) -> dict:
    """
    Analyse nutritional content using with_structured_output(MealAnalysis).
    Skips gracefully if no meals were mentioned (returns safe defaults).
    """
    t0 = time.monotonic()
    signals = state.get("clinical_signals", {})
    meals = signals.get("meals_mentioned", [])

    if not meals:
        elapsed = round((time.monotonic() - t0) * 1000, 2)
        return {
            "meal_data": {
                "estimated_calories": None,
                "carb_load": None,
                "saturated_fat_concern": False,
                "glycemic_concern": False,
                "meal_quality_score": None,
                "flags": [],
                "notes": "No meals reported by patient.",
            },
            "latency_ms": {**state.get("latency_ms", {}), "meal_analysis": elapsed},
        }

    structured_llm = _get_llm_fast().with_structured_output(MealAnalysis)

    try:
        result: MealAnalysis = structured_llm.invoke([
            {"role": "system", "content": _MEAL_SYSTEM},
            {"role": "user", "content": f"Patient reported eating: {', '.join(meals)}"},
        ])
        meal_data = result.model_dump()
    except Exception as exc:
        logger.warning("meal_analysis structured output failed: %s", exc)
        meal_data = {
            "estimated_calories": None, "carb_load": None,
            "saturated_fat_concern": False, "glycemic_concern": False,
            "meal_quality_score": None, "flags": [],
            "notes": "Meal analysis unavailable.",
        }

    elapsed = round((time.monotonic() - t0) * 1000, 2)
    logger.info("meal_analysis: %.0f ms | glycemic_concern=%s",
                elapsed, meal_data.get("glycemic_concern"))
    return {
        "meal_data": meal_data,
        "latency_ms": {**state.get("latency_ms", {}), "meal_analysis": elapsed},
    }


# ---------------------------------------------------------------------------
# Node 4 — risk_flag  (DETERMINISTIC PYTHON — NO LLM)
# ---------------------------------------------------------------------------

_CRITICAL_KEYWORDS = [
    "chest pain",
    "can't breathe",
    "cannot breathe",
    "difficulty breathing",
    "severe headache",
    "vision loss",
    "arm pain",
    "jaw pain",
    "suicidal",
    "self harm",
    "self-harm",
    "overdose",
]


def risk_flag(state: AgentState) -> dict:
    """
    PURE PYTHON safety gate — absolutely no LLM involvement.

    Priority order (first match wins for CRITICAL/HIGH):
      CRITICAL  — any critical keyword in raw transcript
      HIGH      — extraction failed (uncertain data = unsafe to assume LOW)
                  OR missed_doses=True AND symptoms present
      MEDIUM    — glycemic_concern=True AND no exercise reported
      LOW       — default

    requires_human_review=True for HIGH or CRITICAL.
    """
    t0 = time.monotonic()

    transcript_lower = state.get("transcript", "").lower()
    signals = state.get("clinical_signals", {})
    meal_data = state.get("meal_data", {})
    extraction_failed = state.get("extraction_failed", False)

    reasons: list[str] = []
    risk_level = RiskLevel.LOW

    # --- CRITICAL: keyword scan of raw transcript ---
    for keyword in _CRITICAL_KEYWORDS:
        if keyword in transcript_lower:
            risk_level = RiskLevel.CRITICAL
            reasons.append(f"Critical keyword detected: '{keyword}'")

    # --- HIGH: extraction failure (unsafe to proceed on unknown data) ---
    if risk_level != RiskLevel.CRITICAL and extraction_failed:
        risk_level = RiskLevel.HIGH
        reasons.append("Clinical signal extraction failed — routing for human review")

    # --- HIGH: missed doses + active symptoms ---
    if risk_level != RiskLevel.CRITICAL and risk_level != RiskLevel.HIGH:
        missed = signals.get("missed_doses", False)
        symptoms = signals.get("symptoms", [])
        if missed and symptoms:
            risk_level = RiskLevel.HIGH
            reasons.append("Missed doses with active symptoms reported")

    # --- MEDIUM: glycemic concern without exercise ---
    if risk_level == RiskLevel.LOW:
        if meal_data.get("glycemic_concern", False) and not signals.get("exercise_reported", False):
            risk_level = RiskLevel.MEDIUM
            reasons.append("Glycemic concern with no exercise reported")

    if not reasons:
        reasons.append("No risk factors identified")

    requires_human_review = risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
    elapsed = round((time.monotonic() - t0) * 1000, 2)

    logger.info("risk_flag: %s | review=%s | reasons=%s | %.0f ms",
                risk_level.value, requires_human_review, reasons, elapsed)
    return {
        "risk_level": risk_level,
        "risk_reasons": reasons,
        "requires_human_review": requires_human_review,
        "latency_ms": {**state.get("latency_ms", {}), "risk_flag": elapsed},
    }


# ---------------------------------------------------------------------------
# Node 5 — human_review_gate
# ---------------------------------------------------------------------------

def human_review_gate(state: AgentState) -> dict:
    """
    True human-in-the-loop gate using LangGraph NodeInterrupt.

    Raises NodeInterrupt which:
      1. Immediately pauses graph execution at this node
      2. Persists the full state snapshot to the MemorySaver checkpointer
      3. Returns control to the calling code (main.py catches GraphInterrupt)

    Resumption: call graph.invoke(None, config={"configurable": {"thread_id": job_id}})
    after a clinician approves the case. The graph continues from this exact
    point — no earlier nodes are re-executed.
    """
    t0 = time.monotonic()
    risk_level = state.get("risk_level", RiskLevel.LOW)
    risk_str = risk_level.value if isinstance(risk_level, RiskLevel) else str(risk_level)
    reasons = state.get("risk_reasons", [])

    note = (
        f"⚠️ ESCALATED FOR HUMAN REVIEW — Risk: {risk_str.upper()}. "
        f"Reasons: {'; '.join(reasons)}. "
        "Awaiting clinician approval before summary is generated."
    )

    logger.warning("HUMAN REVIEW REQUIRED — patient=%s risk=%s",
                   state.get("patient_id", "unknown"), risk_str)

    elapsed = round((time.monotonic() - t0) * 1000, 2)

    # Persist the review note to state before interrupting so it's available
    # in the checkpointed snapshot that main.py surfaces to the dashboard.
    # NodeInterrupt pauses here; generate_summary runs only after approval.
    raise NodeInterrupt({
        "note": note,
        "latency_ms": {**state.get("latency_ms", {}), "human_review_gate": elapsed},
    })


# ---------------------------------------------------------------------------
# Node 6 — generate_summary
# ---------------------------------------------------------------------------

_SUMMARY_SYSTEM = """You are a clinical documentation assistant producing structured summaries for licensed clinicians.
Write a concise, professional markdown summary using exactly these sections:

## Patient Check-In Summary
## Key Findings
## Nutritional Assessment
## Action Items
## Patient Concerns

Be factual, clinical, and precise. Do not invent information not present in the input.
If a human review was required, begin with a prominent ⚠️ ESCALATION NOTICE."""


def generate_summary(state: AgentState) -> dict:
    """Use full-quality Claude to produce a structured markdown clinical summary."""
    t0 = time.monotonic()

    signals = state.get("clinical_signals", {})
    meal_data = state.get("meal_data", {})
    risk_level = state.get("risk_level", RiskLevel.LOW)
    risk_str = risk_level.value if isinstance(risk_level, RiskLevel) else str(risk_level)
    risk_reasons = state.get("risk_reasons", [])
    review_note = state.get("human_review_note", "")
    transcript = state.get("transcript", "")
    patient_id = state.get("patient_id", "unknown")

    import json
    user_content = f"""Patient ID: {patient_id}
Risk Level: {risk_str.upper()}
Risk Reasons: {'; '.join(risk_reasons)}
Human Review Required: {state.get('requires_human_review', False)}
{f'Clinician Review Note: {review_note}' if review_note else ''}

Clinical Signals:
{json.dumps(signals, indent=2)}

Meal / Nutritional Data:
{json.dumps(meal_data, indent=2)}

Original Transcript:
{transcript}
"""

    response = _get_llm().invoke([
        {"role": "system", "content": _SUMMARY_SYSTEM},
        {"role": "user", "content": user_content},
    ])

    elapsed = round((time.monotonic() - t0) * 1000, 2)
    logger.info("generate_summary: %.0f ms", elapsed)
    return {
        "clinical_summary": response.content,
        "latency_ms": {**state.get("latency_ms", {}), "generate_summary": elapsed},
    }


# ---------------------------------------------------------------------------
# Conditional edge router
# ---------------------------------------------------------------------------

def _route_after_risk(state: AgentState) -> str:
    if state.get("requires_human_review", False):
        return "human_review_gate"
    return "generate_summary"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_graph(checkpointer=None) -> Any:
    """
    Compile and return the LangGraph intake pipeline.

    Args:
        checkpointer: Optional LangGraph checkpointer. Pass MemorySaver() for
                      NodeInterrupt + resumption support. If None, NodeInterrupt
                      will still fire but state cannot be resumed.
    """
    builder = StateGraph(AgentState)

    builder.add_node("transcribe", transcribe)
    builder.add_node("extract_signals", extract_signals)
    builder.add_node("meal_analysis", meal_analysis)
    builder.add_node("risk_flag", risk_flag)
    builder.add_node("human_review_gate", human_review_gate)
    builder.add_node("generate_summary", generate_summary)

    builder.set_entry_point("transcribe")
    builder.add_edge("transcribe", "extract_signals")
    builder.add_edge("extract_signals", "meal_analysis")
    builder.add_edge("meal_analysis", "risk_flag")
    builder.add_conditional_edges(
        "risk_flag",
        _route_after_risk,
        {
            "human_review_gate": "human_review_gate",
            "generate_summary": "generate_summary",
        },
    )
    builder.add_edge("human_review_gate", "generate_summary")
    builder.add_edge("generate_summary", END)

    return builder.compile(checkpointer=checkpointer)


# Module-level checkpointer and compiled graph
# main.py imports `graph` and `checkpointer` directly.
checkpointer = MemorySaver()
graph = build_graph(checkpointer=checkpointer)
