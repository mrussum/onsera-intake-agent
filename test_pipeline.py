"""
Onsera Health — Pipeline Test Suite

Tests the full LangGraph pipeline using mock transcripts (no audio file or
microphone required). The transcribe node is patched to inject a transcript
directly into state, bypassing Groq.

Usage:
    python test_pipeline.py

Requirements:
    - .env file present with valid ANTHROPIC_API_KEY (sk-ant-...) and GROQ_API_KEY (gsk_...)
    - pip install -r backend/requirements.txt
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
            f"Got: '{anthropic_key[:12]}...'" if anthropic_key else
            "ANTHROPIC_API_KEY is not set."
        )
    if not groq_key.startswith("gsk_"):
        errors.append(
            f"GROQ_API_KEY is missing or invalid (must start with 'gsk_'). "
            f"Got: '{groq_key[:8]}...'" if groq_key else
            "GROQ_API_KEY is not set."
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
# Build mock transcribe node factory
# ---------------------------------------------------------------------------

def make_mock_transcribe(transcript: str):
    """Return a transcribe replacement that injects `transcript` directly."""
    def mock_transcribe(state):
        latency = state.get("latency_ms", {})
        latency["transcribe"] = 0.0  # Mocked — no actual call
        return {"transcript": transcript, "latency_ms": latency}
    return mock_transcribe


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def run_test(
    test_name: str,
    transcript: str,
    assertions: list,
) -> bool:
    """
    Patch the transcribe node with a mock, run the pipeline, evaluate assertions.
    Returns True if all assertions pass.
    """
    print(f"{'─' * 60}")
    print(f"  {test_name}")
    print(f"{'─' * 60}")
    print(f"  Transcript: {transcript[:100]}…")

    # Create a dummy audio file (won't be read — transcribe is mocked)
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
        f.write(b"MOCK_AUDIO")
        audio_path = f.name

    from agents.intake_graph import AgentState, build_graph

    t_start = time.monotonic()

    # Patch at the module level so the compiled graph picks up the mock
    with patch("agents.intake_graph.transcribe", make_mock_transcribe(transcript)):
        # Rebuild the graph so the patched node is wired in
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

    elapsed = round((time.monotonic() - t_start) * 1000)
    os.unlink(audio_path)

    risk_level = result.get("risk_level", "low")
    if hasattr(risk_level, "value"):
        risk_level = risk_level.value

    print(f"\n  Results:")
    print(f"    risk_level          = {risk_level}")
    print(f"    requires_human_review = {result.get('requires_human_review')}")
    print(f"    risk_reasons        = {result.get('risk_reasons')}")
    print(f"    latency_ms          = {result.get('latency_ms')}")
    print(f"    total elapsed       = {elapsed}ms")

    # Evaluate assertions
    passed = True
    for label, actual, expected in assertions:
        ok = actual == expected
        symbol = "✓" if ok else "✗"
        print(f"\n    {symbol} {label}")
        print(f"      expected: {expected!r}")
        print(f"      actual:   {actual!r}")
        if not ok:
            passed = False

    status = "PASSED" if passed else "FAILED"
    print(f"\n  ── {test_name}: {status} ──\n")
    return passed


# ---------------------------------------------------------------------------
# TEST 1: Normal intake — no risk flags expected
# ---------------------------------------------------------------------------

TRANSCRIPT_NORMAL = (
    "Hi, this is Sarah, patient ID P2001. I've been taking my metformin 500mg every "
    "morning this week without missing any doses. For breakfast today I had two eggs "
    "and some toast with a bit of butter, and a glass of orange juice. Lunch was a "
    "chicken salad. I've been feeling a bit tired lately but nothing serious. "
    "I slept about 7 hours last night. No major concerns from my end."
)

# ---------------------------------------------------------------------------
# TEST 2: Critical intake — chest pain + missed medication
# ---------------------------------------------------------------------------

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
    print("  Onsera Health — Pipeline Test Suite")
    print("=" * 60)
    print()

    results = []

    # --- TEST 1 ---
    result_1 = run_test(
        test_name="TEST 1: Normal intake (metformin, eggs/toast, tired)",
        transcript=TRANSCRIPT_NORMAL,
        assertions=[
            (
                "requires_human_review should be False",
                None,  # placeholder — filled below
                False,
            ),
        ],
    )
    # Re-run with proper assertion capture
    from agents.intake_graph import AgentState, build_graph
    import tempfile, os as _os
    from unittest.mock import patch as _patch

    def _run_and_capture(transcript):
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
            f.write(b"MOCK")
            ap = f.name
        with _patch("agents.intake_graph.transcribe", make_mock_transcribe(transcript)):
            g = build_graph()
            s: AgentState = {
                "audio_path": ap, "patient_id": "TEST",
                "transcript": "", "clinical_signals": {}, "meal_data": {},
                "risk_level": "low", "risk_reasons": [], "clinical_summary": "",
                "requires_human_review": False, "human_review_note": "",
                "latency_ms": {}, "messages": [],
            }
            r = g.invoke(s)
        _os.unlink(ap)
        rl = r.get("risk_level", "low")
        if hasattr(rl, "value"):
            rl = rl.value
        return r, rl

    print("=" * 60)
    print("  Running assertions...")
    print("=" * 60)
    print()

    all_passed = True

    # Test 1
    print("TEST 1: Normal intake — metformin, eggs and toast, feeling tired")
    print("─" * 60)
    r1, rl1 = _run_and_capture(TRANSCRIPT_NORMAL)
    review1 = r1.get("requires_human_review", False)
    print(f"  risk_level            = {rl1}")
    print(f"  requires_human_review = {review1}")
    t1_ok = not review1
    sym = "✓" if t1_ok else "✗"
    print(f"  {sym} requires_human_review == False  (actual: {review1})")
    print(f"  {'PASSED' if t1_ok else 'FAILED'}\n")
    all_passed = all_passed and t1_ok

    # Test 2
    print("TEST 2: Critical intake — chest pain, arm pain, missed medication")
    print("─" * 60)
    r2, rl2 = _run_and_capture(TRANSCRIPT_CRITICAL)
    review2 = r2.get("requires_human_review", False)
    print(f"  risk_level            = {rl2}")
    print(f"  requires_human_review = {review2}")
    t2_review_ok = review2 is True
    t2_risk_ok = rl2 == "critical"
    sym_r = "✓" if t2_review_ok else "✗"
    sym_l = "✓" if t2_risk_ok else "✗"
    print(f"  {sym_r} requires_human_review == True    (actual: {review2})")
    print(f"  {sym_l} risk_level == 'critical'         (actual: {rl2})")
    t2_ok = t2_review_ok and t2_risk_ok
    print(f"  {'PASSED' if t2_ok else 'FAILED'}\n")
    all_passed = all_passed and t2_ok

    # Final summary
    print("=" * 60)
    if all_passed:
        print("  ALL TESTS PASSED ✓")
    else:
        print("  SOME TESTS FAILED ✗ — review output above")
    print("=" * 60)
    sys.exit(0 if all_passed else 1)
