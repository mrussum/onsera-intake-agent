"""
Onsera Health — Pipeline Integration Test Suite

Tests the full LangGraph pipeline using mock transcripts (no audio file or
microphone required). The transcribe node is patched to inject a transcript
directly into state, bypassing Groq.

Usage:
    python test_pipeline.py

Requirements:
    - .env file present with valid ANTHROPIC_API_KEY (sk-ant-...) and GROQ_API_KEY (gsk_...)
    - pip install -r backend/requirements.txt  (run from repo root)
"""

import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

# Allow imports from backend/ when running from repo root
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# Pre-flight: validate API keys before touching LangGraph
# ---------------------------------------------------------------------------

def check_env() -> None:
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    groq_key = os.getenv("GROQ_API_KEY", "")

    errors = []
    if not anthropic_key.startswith("sk-ant-"):
        errors.append(
            f"ANTHROPIC_API_KEY is missing or invalid (must start with 'sk-ant-'). "
            + (f"Got: '{anthropic_key[:12]}...'" if anthropic_key else "Not set.")
        )
    if not groq_key.startswith("gsk_"):
        errors.append(
            f"GROQ_API_KEY is missing or invalid (must start with 'gsk_'). "
            + (f"Got: '{groq_key[:8]}...'" if groq_key else "Not set.")
        )

    if errors:
        print("\n❌  Environment check failed:")
        for e in errors:
            print(f"   • {e}")
        print("\nCopy .env.example to .env and add your API keys, then re-run.")
        sys.exit(1)

    print("✓  API keys validated")
    print(f"   ANTHROPIC_API_KEY: {anthropic_key[:12]}…")
    print(f"   GROQ_API_KEY:      {groq_key[:8]}…\n")


check_env()


# ---------------------------------------------------------------------------
# Mock transcribe node factory
# ---------------------------------------------------------------------------

def make_mock_transcribe(transcript: str):
    """Return a transcribe replacement that injects `transcript` directly into state."""
    def mock_transcribe(state):
        latency = state.get("latency_ms", {})
        latency["transcribe"] = 0.0  # Mocked — no actual Groq call
        return {"transcript": transcript, "latency_ms": latency}
    return mock_transcribe


# ---------------------------------------------------------------------------
# Pipeline runner (patches transcribe, runs full graph)
# ---------------------------------------------------------------------------

def run_pipeline(transcript: str) -> dict:
    """
    Patch the transcribe node with a mock, run the full pipeline, return result.
    The graph is rebuilt inside the patch context so the mock is wired in.
    """
    from agents.intake_graph import AgentState, build_graph

    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
        f.write(b"MOCK_AUDIO")
        audio_path = f.name

    try:
        with patch("agents.intake_graph.transcribe", make_mock_transcribe(transcript)):
            g = build_graph()
            initial_state: AgentState = {
                "audio_path": audio_path,
                "patient_id": "TEST-PATIENT",
                "transcript": "",
                "clinical_signals": {},
                "meal_data": {},
                "risk_level": "low",
                "risk_reasons": [],
                "clinical_summary": "",
                "requires_human_review": False,
                "human_review_note": "",
                "latency_ms": {},
                "messages": [],
            }
            result = g.invoke(initial_state)
    finally:
        os.unlink(audio_path)

    # Normalise RiskLevel enum → string
    risk_level = result.get("risk_level", "low")
    if hasattr(risk_level, "value"):
        risk_level = risk_level.value
    result["risk_level"] = risk_level

    return result


# ---------------------------------------------------------------------------
# Test transcripts
# ---------------------------------------------------------------------------

TRANSCRIPT_NORMAL = (
    "Hi, this is Sarah, patient ID P2001. I've been taking my metformin 500mg every "
    "morning this week without missing any doses. For breakfast today I had two eggs "
    "and some toast with a bit of butter, and a glass of orange juice. Lunch was a "
    "chicken salad. I've been feeling a bit tired lately but nothing serious. "
    "I slept about 7 hours last night. No major concerns from my end."
)

TRANSCRIPT_CRITICAL = (
    "Hi, this is Robert, patient P3007. I need to report something urgent. I've been "
    "having chest pain since early this morning. I also have some arm pain and jaw pain "
    "which started about an hour ago. I forgot to take my aspirin and my blood pressure "
    "medication yesterday and today. I haven't been able to eat much. Please someone "
    "needs to call me back right away. I'm really worried."
)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("  Onsera Health — Pipeline Integration Tests")
    print("=" * 60)
    print()

    all_passed = True

    # -----------------------------------------------------------------------
    # TEST 1: Normal intake — low/medium risk, no human review
    # -----------------------------------------------------------------------
    print("TEST 1: Normal intake — metformin, eggs and toast, feeling tired")
    print("─" * 60)
    t0 = time.monotonic()
    r1 = run_pipeline(TRANSCRIPT_NORMAL)
    elapsed1 = round((time.monotonic() - t0) * 1000)

    print(f"  risk_level            = {r1['risk_level']}")
    print(f"  requires_human_review = {r1['requires_human_review']}")
    print(f"  risk_reasons          = {r1['risk_reasons']}")
    print(f"  latency_ms            = {r1['latency_ms']}")
    print(f"  elapsed               = {elapsed1}ms")
    print()

    t1_ok = r1["requires_human_review"] is False
    sym = "✓" if t1_ok else "✗"
    print(f"  {sym} requires_human_review == False  (actual: {r1['requires_human_review']})")
    print(f"  {'PASSED' if t1_ok else 'FAILED'}\n")
    all_passed = all_passed and t1_ok

    # -----------------------------------------------------------------------
    # TEST 2: Critical intake — chest pain + missed medication
    # -----------------------------------------------------------------------
    print("TEST 2: Critical intake — chest pain, arm pain, missed medication")
    print("─" * 60)
    t0 = time.monotonic()
    r2 = run_pipeline(TRANSCRIPT_CRITICAL)
    elapsed2 = round((time.monotonic() - t0) * 1000)

    print(f"  risk_level            = {r2['risk_level']}")
    print(f"  requires_human_review = {r2['requires_human_review']}")
    print(f"  risk_reasons          = {r2['risk_reasons']}")
    print(f"  latency_ms            = {r2['latency_ms']}")
    print(f"  elapsed               = {elapsed2}ms")
    print()

    t2_review_ok = r2["requires_human_review"] is True
    t2_risk_ok = r2["risk_level"] == "critical"
    sym_r = "✓" if t2_review_ok else "✗"
    sym_l = "✓" if t2_risk_ok else "✗"
    print(f"  {sym_r} requires_human_review == True    (actual: {r2['requires_human_review']})")
    print(f"  {sym_l} risk_level == 'critical'         (actual: {r2['risk_level']})")
    t2_ok = t2_review_ok and t2_risk_ok
    print(f"  {'PASSED' if t2_ok else 'FAILED'}\n")
    all_passed = all_passed and t2_ok

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print("=" * 60)
    if all_passed:
        print("  ALL TESTS PASSED ✓")
    else:
        print("  SOME TESTS FAILED ✗ — review output above")
    print("=" * 60)
    sys.exit(0 if all_passed else 1)
