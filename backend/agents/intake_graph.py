"""
Onsera Health — Patient Intake LangGraph Pipeline

Six-node agentic pipeline:
  transcribe → extract_signals → meal_analysis → risk_flag
      → [human_review_gate] → generate_summary → END

Clinical AI design principles:
  - Safety decisions (risk_flag) are ALWAYS deterministic Python — never LLM.
  - Human-in-the-loop routing via conditional edge on requires_human_review.
  - Defensive JSON parsing strips markdown fences from LLM output.
  - Every node records its latency for observability.
"""

import json
import logging
import os
import time
from enum import Enum
from typing import Annotated, Any

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
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
    latency_ms: dict
    messages: Annotated[list[BaseMessage], add_messages]


# ---------------------------------------------------------------------------
# LLM clients (lazy-initialised so the module can be imported without keys)
# ---------------------------------------------------------------------------

_claude_model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5")
_llm_fast: ChatAnthropic | None = None
_llm: ChatAnthropic | None = None


def _get_llm_fast() -> ChatAnthropic:
    global _llm_fast
    if _llm_fast is None:
        _llm_fast = ChatAnthropic(
            model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5"),
            temperature=0,
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        )
    return _llm_fast


def _get_llm() -> ChatAnthropic:
    global _llm
    if _llm is None:
        _llm = ChatAnthropic(
            model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5"),
            temperature=0.3,
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        )
    return _llm


# ---------------------------------------------------------------------------
# Helper: strip markdown code fences before JSON parsing
# ---------------------------------------------------------------------------

def _parse_json_response(content: str) -> dict:
    """
    Defensively parse JSON from an LLM response.
    Handles cases where Claude wraps output in ```json ... ``` fences.
    """
    text = content.strip()
    # Strip opening fence
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
    # Strip closing fence
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    return json.loads(text.strip())


# ---------------------------------------------------------------------------
# Node 1 — transcribe
# ---------------------------------------------------------------------------

def transcribe(state: AgentState) -> dict:
    """
    Transcribe audio using Groq Whisper (whisper-large-v3).
    Reads GROQ_API_KEY from the environment.
    """
    t0 = time.monotonic()

    from groq import Groq

    groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    audio_path = state["audio_path"]

    with open(audio_path, "rb") as audio_file:
        transcription = groq_client.audio.transcriptions.create(
            model="whisper-large-v3",
            file=audio_file,
            response_format="text",
        )

    transcript = transcription if isinstance(transcription, str) else transcription.text

    latency = state.get("latency_ms", {})
    latency["transcribe"] = round((time.monotonic() - t0) * 1000, 2)

    logger.info("transcribe: %.0f ms | %d chars", latency["transcribe"], len(transcript))
    return {"transcript": transcript, "latency_ms": latency}


# ---------------------------------------------------------------------------
# Node 2 — extract_signals
# ---------------------------------------------------------------------------

_EXTRACT_SYSTEM = """You are a clinical NLP assistant. Extract structured clinical signals from the patient transcript below.
Return ONLY valid JSON with exactly these fields (no extra text, no markdown fences):
{
  "symptoms": ["list of symptoms mentioned"],
  "medications": [{"name": "...", "dose": "...", "adherent": true}],
  "meals_mentioned": ["list of foods/meals described"],
  "weight_change": "gain | loss | stable | null",
  "exercise_reported": true,
  "mood": "string description or null",
  "sleep_hours": 7.5,
  "concerns": ["list of patient concerns"],
  "missed_doses": false
}
Use null for missing numeric fields. missed_doses must be a boolean."""


def extract_signals(state: AgentState) -> dict:
    """Use llm_fast (temperature=0) to extract structured clinical signals."""
    t0 = time.monotonic()

    transcript = state.get("transcript", "")
    response = _get_llm_fast().invoke(
        [
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user", "content": f"Transcript:\n{transcript}"},
        ]
    )

    try:
        signals = _parse_json_response(response.content)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("extract_signals JSON parse failed: %s", exc)
        signals = {
            "symptoms": [],
            "medications": [],
            "meals_mentioned": [],
            "weight_change": None,
            "exercise_reported": False,
            "mood": None,
            "sleep_hours": None,
            "concerns": [],
            "missed_doses": False,
        }

    latency = state.get("latency_ms", {})
    latency["extract_signals"] = round((time.monotonic() - t0) * 1000, 2)

    logger.info("extract_signals: %.0f ms", latency["extract_signals"])
    return {"clinical_signals": signals, "latency_ms": latency}


# ---------------------------------------------------------------------------
# Node 3 — meal_analysis
# ---------------------------------------------------------------------------

_MEAL_SYSTEM = """You are a clinical dietitian assistant. Analyse the nutritional content of the meals described.
Return ONLY valid JSON with exactly these fields (no extra text, no markdown fences):
{
  "estimated_calories": 1800,
  "carb_load": "low | moderate | high",
  "saturated_fat_concern": false,
  "glycemic_concern": false,
  "meal_quality_score": 7,
  "flags": ["list of dietary flags"],
  "notes": "brief clinical note"
}
meal_quality_score is 1 (very poor) to 10 (excellent). Use integer values."""


def meal_analysis(state: AgentState) -> dict:
    """
    Analyse nutritional content with llm_fast.
    Skips gracefully if no meals were mentioned upstream.
    """
    t0 = time.monotonic()
    latency = state.get("latency_ms", {})

    signals = state.get("clinical_signals", {})
    meals = signals.get("meals_mentioned", [])

    if not meals:
        latency["meal_analysis"] = round((time.monotonic() - t0) * 1000, 2)
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
            "latency_ms": latency,
        }

    meals_text = ", ".join(meals)
    response = _get_llm_fast().invoke(
        [
            {"role": "system", "content": _MEAL_SYSTEM},
            {"role": "user", "content": f"Patient reported eating: {meals_text}"},
        ]
    )

    try:
        meal_data = _parse_json_response(response.content)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("meal_analysis JSON parse failed: %s", exc)
        meal_data = {
            "estimated_calories": None,
            "carb_load": None,
            "saturated_fat_concern": False,
            "glycemic_concern": False,
            "meal_quality_score": None,
            "flags": [],
            "notes": "Meal analysis could not be parsed.",
        }

    latency["meal_analysis"] = round((time.monotonic() - t0) * 1000, 2)
    logger.info("meal_analysis: %.0f ms", latency["meal_analysis"])
    return {"meal_data": meal_data, "latency_ms": latency}


# ---------------------------------------------------------------------------
# Node 4 — risk_flag  (DETERMINISTIC PYTHON — NO LLM)
# ---------------------------------------------------------------------------

# Critical keyword phrases — checked against lowercased transcript
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
    PURE PYTHON safety gate — no LLM involvement.

    Risk stratification rules (applied in priority order):
      CRITICAL  — any critical keyword detected in transcript
      HIGH      — missed_doses=True AND symptoms present
      MEDIUM    — glycemic_concern=True AND no exercise reported
      LOW       — default

    Sets requires_human_review=True for HIGH or CRITICAL.
    """
    t0 = time.monotonic()

    transcript_lower = state.get("transcript", "").lower()
    signals = state.get("clinical_signals", {})
    meal_data = state.get("meal_data", {})

    reasons: list[str] = []
    risk_level = RiskLevel.LOW

    # --- CRITICAL check ---
    for keyword in _CRITICAL_KEYWORDS:
        if keyword in transcript_lower:
            risk_level = RiskLevel.CRITICAL
            reasons.append(f"Critical keyword detected: '{keyword}'")

    # --- HIGH check (only if not already CRITICAL) ---
    if risk_level != RiskLevel.CRITICAL:
        missed = signals.get("missed_doses", False)
        symptoms = signals.get("symptoms", [])
        if missed and symptoms:
            risk_level = RiskLevel.HIGH
            reasons.append("Missed doses with active symptoms reported")

    # --- MEDIUM check (only if still LOW) ---
    if risk_level == RiskLevel.LOW:
        glycemic_concern = meal_data.get("glycemic_concern", False)
        exercise = signals.get("exercise_reported", False)
        if glycemic_concern and not exercise:
            risk_level = RiskLevel.MEDIUM
            reasons.append("Glycemic concern with no exercise reported")

    if not reasons:
        reasons.append("No risk factors identified")

    requires_human_review = risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)

    latency = state.get("latency_ms", {})
    latency["risk_flag"] = round((time.monotonic() - t0) * 1000, 2)

    logger.info(
        "risk_flag: %s | review=%s | %.0f ms",
        risk_level.value,
        requires_human_review,
        latency["risk_flag"],
    )
    return {
        "risk_level": risk_level,
        "risk_reasons": reasons,
        "requires_human_review": requires_human_review,
        "latency_ms": latency,
    }


# ---------------------------------------------------------------------------
# Node 5 — human_review_gate
# ---------------------------------------------------------------------------

def human_review_gate(state: AgentState) -> dict:
    """
    Human-in-the-loop routing gate.

    In production this node would raise NodeInterrupt to pause the graph
    and surface the case in a clinician review queue before continuing.
    Here we log a warning and add a note to state so the downstream summary
    can highlight the escalation.
    """
    t0 = time.monotonic()

    risk_level = state.get("risk_level", RiskLevel.LOW)
    reasons = state.get("risk_reasons", [])

    logger.warning(
        "HUMAN REVIEW REQUIRED — patient_id=%s risk=%s reasons=%s",
        state.get("patient_id", "unknown"),
        risk_level.value if isinstance(risk_level, RiskLevel) else risk_level,
        reasons,
    )

    # In production: raise NodeInterrupt("Awaiting clinician review")
    note = (
        f"⚠️ ESCALATED FOR HUMAN REVIEW — Risk level: {risk_level.value if isinstance(risk_level, RiskLevel) else risk_level}. "
        f"Reasons: {'; '.join(reasons)}. "
        "A clinician must review this intake before it is acted upon."
    )

    latency = state.get("latency_ms", {})
    latency["human_review_gate"] = round((time.monotonic() - t0) * 1000, 2)

    return {"human_review_note": note, "latency_ms": latency}


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
If a human review is required, begin the summary with a prominent ⚠️ ESCALATION NOTICE."""


def generate_summary(state: AgentState) -> dict:
    """Use the full-quality llm to produce a structured markdown clinical summary."""
    t0 = time.monotonic()

    signals = state.get("clinical_signals", {})
    meal_data = state.get("meal_data", {})
    risk_level = state.get("risk_level", RiskLevel.LOW)
    risk_reasons = state.get("risk_reasons", [])
    review_note = state.get("human_review_note", "")
    transcript = state.get("transcript", "")
    patient_id = state.get("patient_id", "unknown")

    risk_str = risk_level.value if isinstance(risk_level, RiskLevel) else str(risk_level)

    user_content = f"""Patient ID: {patient_id}
Risk Level: {risk_str.upper()}
Risk Reasons: {'; '.join(risk_reasons)}
Human Review Required: {state.get('requires_human_review', False)}
{f'Review Note: {review_note}' if review_note else ''}

Clinical Signals:
{json.dumps(signals, indent=2)}

Meal / Nutritional Data:
{json.dumps(meal_data, indent=2)}

Original Transcript:
{transcript}
"""

    response = _get_llm().invoke(
        [
            {"role": "system", "content": _SUMMARY_SYSTEM},
            {"role": "user", "content": user_content},
        ]
    )

    latency = state.get("latency_ms", {})
    latency["generate_summary"] = round((time.monotonic() - t0) * 1000, 2)

    logger.info("generate_summary: %.0f ms", latency["generate_summary"])
    return {"clinical_summary": response.content, "latency_ms": latency}


# ---------------------------------------------------------------------------
# Conditional edge router
# ---------------------------------------------------------------------------

def _route_after_risk(state: AgentState) -> str:
    """Route to human_review_gate if required, otherwise straight to summary."""
    if state.get("requires_human_review", False):
        return "human_review_gate"
    return "generate_summary"


# ---------------------------------------------------------------------------
# Build the graph
# ---------------------------------------------------------------------------

def build_graph() -> Any:
    """Compile and return the LangGraph intake pipeline."""
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

    return builder.compile()


# Singleton compiled graph — import and call graph.invoke(state)
graph = build_graph()
