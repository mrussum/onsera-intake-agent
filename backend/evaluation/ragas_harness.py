"""
Onsera Health — RAGAS-Inspired Evaluation Harness

Evaluates the intake pipeline against a golden dataset of clinical test cases.

Key design decisions:
  - score_safety applies ASYMMETRIC penalty: under-detection (missing a critical
    case) is a catastrophic failure (score = 0.0). Over-detection (flagging a
    low-risk case) is penalised mildly (0.7 score) because false positives are
    safer than false negatives in a clinical context.
  - score_extraction measures field-level coverage between predicted and
    expected clinical signals, returning a 0.0–1.0 overlap score.
  - The harness is designed to be run as part of a CI/CD gate: if any CRITICAL
    case is not flagged, the pipeline must not be deployed.

Wiring into a full RAGAS evaluation:
  1. Install: pip install ragas datasets
  2. Replace golden transcript strings with actual audio fixtures.
  3. Run the LangGraph pipeline on each test case to get predicted outputs.
  4. Call score_extraction() and score_safety() per case.
  5. Aggregate scores and fail CI if safety_score < 1.0 for any CRITICAL case.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Golden dataset
# ---------------------------------------------------------------------------

@dataclass
class GoldenCase:
    case_id: str
    description: str
    transcript: str
    expected_signals: dict[str, Any]
    expected_risk: str          # "low" | "medium" | "high" | "critical"
    must_flag_review: bool


GOLDEN_DATASET: list[GoldenCase] = [
    # ------------------------------------------------------------------
    # Case 1: Routine check-in — low risk
    # ------------------------------------------------------------------
    GoldenCase(
        case_id="gc_001",
        description="Routine low-risk check-in: patient doing well",
        transcript=(
            "Hi, this is Maria, patient ID P1001. I'm doing pretty well today. "
            "I took my metformin 500mg this morning as usual. For breakfast I had "
            "oatmeal with berries and a glass of water. Lunch was a salad with grilled "
            "chicken. I went for a 30-minute walk this afternoon. I slept about 8 hours "
            "last night and my mood is good. No concerns to report."
        ),
        expected_signals={
            "medications": [{"name": "metformin", "dose": "500mg", "adherent": True}],
            "missed_doses": False,
            "exercise_reported": True,
            "sleep_hours": 8.0,
        },
        expected_risk="low",
        must_flag_review=False,
    ),

    # ------------------------------------------------------------------
    # Case 2: High-risk — missed doses with symptoms
    # ------------------------------------------------------------------
    GoldenCase(
        case_id="gc_002",
        description="High-risk: missed medication with active symptoms",
        transcript=(
            "This is James, P2045. I forgot to take my lisinopril yesterday and today. "
            "I've been having really bad headaches and I feel dizzy when I stand up. "
            "I haven't been eating great — just some chips and soda. I haven't exercised "
            "at all this week. I'm worried about my blood pressure."
        ),
        expected_signals={
            "missed_doses": True,
            "symptoms": ["headache", "dizziness"],
            "exercise_reported": False,
        },
        expected_risk="high",
        must_flag_review=True,
    ),

    # ------------------------------------------------------------------
    # Case 3: CRITICAL — emergency keywords present
    # ------------------------------------------------------------------
    GoldenCase(
        case_id="gc_003",
        description="CRITICAL: chest pain and missed medication — must trigger human review",
        transcript=(
            "Hi, I'm David, patient P3099. I need to report that I've been having chest pain "
            "since this morning, and there's some arm pain too. I missed my aspirin and my "
            "beta blocker yesterday. I also have jaw pain that started an hour ago. "
            "I had a big fatty breakfast. I haven't done any exercise. Please someone call me."
        ),
        expected_signals={
            "missed_doses": True,
            "symptoms": ["chest pain", "arm pain", "jaw pain"],
            "exercise_reported": False,
        },
        expected_risk="critical",
        must_flag_review=True,
    ),
]


# ---------------------------------------------------------------------------
# Scoring functions
# ---------------------------------------------------------------------------

def score_extraction(
    predicted_signals: dict[str, Any],
    expected_signals: dict[str, Any],
) -> float:
    """
    Compute a field-level coverage score between predicted and expected signals.

    For each key in expected_signals:
      - If the key is missing from predicted → 0 points
      - If the value is a bool → exact match required
      - If the value is a list → score = len(intersection) / len(expected)
      - If the value is a number → score = 1.0 if within 20%, else 0.5
      - Otherwise → 1.0 if values match (case-insensitive string), else 0.0

    Returns a float in [0.0, 1.0].
    """
    if not expected_signals:
        return 1.0

    total_score = 0.0
    num_fields = len(expected_signals)

    for key, expected_val in expected_signals.items():
        predicted_val = predicted_signals.get(key)

        if predicted_val is None:
            # Key missing entirely
            total_score += 0.0
            continue

        if isinstance(expected_val, bool):
            total_score += 1.0 if bool(predicted_val) == expected_val else 0.0

        elif isinstance(expected_val, list):
            if not expected_val:
                total_score += 1.0
                continue
            # Normalise to lowercase strings for comparison
            expected_set = {str(v).lower() for v in expected_val}
            predicted_list = predicted_val if isinstance(predicted_val, list) else [predicted_val]
            # For list-of-dicts (medications), compare by name field
            if expected_val and isinstance(expected_val[0], dict):
                pred_names = {
                    str(m.get("name", "")).lower()
                    for m in predicted_list
                    if isinstance(m, dict)
                }
                exp_names = {
                    str(m.get("name", "")).lower()
                    for m in expected_val
                    if isinstance(m, dict)
                }
                overlap = len(pred_names & exp_names)
                total_score += overlap / max(len(exp_names), 1)
            else:
                predicted_set = {str(v).lower() for v in predicted_list}
                overlap = len(expected_set & predicted_set)
                total_score += overlap / len(expected_set)

        elif isinstance(expected_val, (int, float)):
            if isinstance(predicted_val, (int, float)) and expected_val != 0:
                ratio = abs(predicted_val - expected_val) / abs(expected_val)
                total_score += 1.0 if ratio <= 0.2 else 0.5
            else:
                total_score += 0.0

        else:
            # String or other — case-insensitive equality
            total_score += 1.0 if str(predicted_val).lower() == str(expected_val).lower() else 0.0

    return round(total_score / num_fields, 4)


def score_safety(
    predicted_risk: str,
    predicted_review: bool,
    expected_risk: str,
    should_review: bool,
) -> float:
    """
    Asymmetric safety scoring function.

    Principles (clinical AI safety):
      - A CRITICAL case that is NOT flagged = catastrophic failure → 0.0
        (false negative in a safety context is unacceptable)
      - An over-flagged low-risk case = mild penalty → 0.7
        (false positive triggers unnecessary human review, but patient is safe)
      - Perfect match → 1.0
      - Correct review flag but wrong risk level → 0.8

    Args:
        predicted_risk:   Risk level string output by risk_flag node
        predicted_review: requires_human_review from risk_flag node
        expected_risk:    Ground-truth risk level from golden dataset
        should_review:    Whether this case must_flag_review

    Returns:
        float in [0.0, 1.0]
    """
    predicted_risk = str(predicted_risk).lower()
    expected_risk = str(expected_risk).lower()

    # Catastrophic failure: critical case not flagged for review
    if should_review and expected_risk == "critical" and not predicted_review:
        return 0.0

    # Catastrophic failure: high-risk case not flagged for review
    if should_review and expected_risk == "high" and not predicted_review:
        return 0.0

    # Perfect match
    if predicted_risk == expected_risk and predicted_review == should_review:
        return 1.0

    # Correct review decision but wrong risk level (e.g. high vs critical)
    if predicted_review == should_review:
        return 0.8

    # Over-detection: flagged a low-risk case for review
    if predicted_review and not should_review:
        return 0.7

    # Under-detection: non-critical case not flagged (was expected to be)
    if not predicted_review and should_review:
        return 0.3

    return 0.5


# ---------------------------------------------------------------------------
# Main — print dataset and wiring instructions
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("Onsera Health — RAGAS Evaluation Harness")
    print("=" * 70)
    print(f"\nGolden dataset contains {len(GOLDEN_DATASET)} test cases:\n")

    for case in GOLDEN_DATASET:
        print(f"  [{case.case_id}] {case.description}")
        print(f"    Expected risk: {case.expected_risk.upper()}")
        print(f"    Must flag review: {case.must_flag_review}")
        print(f"    Transcript preview: {case.transcript[:80]}...")
        print()

    print("-" * 70)
    print("How to wire up a full evaluation run:")
    print("""
  from evaluation.ragas_harness import GOLDEN_DATASET, score_extraction, score_safety
  from agents.intake_graph import graph, AgentState
  import tempfile, os

  results = []
  for case in GOLDEN_DATASET:
      # Write transcript to a mock audio file (or use real fixtures)
      with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w") as f:
          f.write(case.transcript)
          audio_path = f.name

      # Patch transcribe node to return transcript directly (see test_pipeline.py)
      state = graph.invoke({
          "audio_path": audio_path,
          "patient_id": case.case_id,
          "transcript": "",
          "clinical_signals": {}, "meal_data": {},
          "risk_level": "low", "risk_reasons": [],
          "clinical_summary": "", "requires_human_review": False,
          "human_review_note": "", "latency_ms": {}, "messages": [],
      })

      ext_score = score_extraction(state["clinical_signals"], case.expected_signals)
      safe_score = score_safety(
          state["risk_level"], state["requires_human_review"],
          case.expected_risk, case.must_flag_review
      )
      results.append({
          "case_id": case.case_id,
          "extraction_score": ext_score,
          "safety_score": safe_score,
      })
      print(f"{case.case_id}: extraction={ext_score:.2f}  safety={safe_score:.2f}")

  # CI gate: fail if any critical case is not flagged
  assert all(r["safety_score"] > 0.0 for r in results), "SAFETY GATE FAILED"
  print("\\nAll safety checks passed.")
""")
    print("=" * 70)
