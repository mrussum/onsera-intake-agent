"""
Unit tests for the risk_flag node.

risk_flag is pure Python (no LLM) so these tests run without API keys.
They import the function directly from agents.intake_graph and exercise
every branch of the priority logic.
"""

import pytest
from agents.intake_graph import RiskLevel, risk_flag


def _state(**kwargs) -> dict:
    """Build a minimal AgentState dict, overridable via kwargs."""
    base = {
        "audio_path": "",
        "patient_id": "TEST",
        "transcript": "",
        "clinical_signals": {},
        "meal_data": {},
        "risk_level": RiskLevel.LOW,
        "risk_reasons": [],
        "clinical_summary": "",
        "requires_human_review": False,
        "human_review_note": "",
        "extraction_failed": False,
        "latency_ms": {},
        "messages": [],
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# CRITICAL — keyword detection
# ---------------------------------------------------------------------------

class TestCriticalKeywords:
    def test_chest_pain_triggers_critical(self):
        result = risk_flag(_state(transcript="I have been having chest pain all day"))
        assert result["risk_level"] == RiskLevel.CRITICAL
        assert result["requires_human_review"] is True
        assert any("chest pain" in r for r in result["risk_reasons"])

    def test_arm_pain_triggers_critical(self):
        result = risk_flag(_state(transcript="my arm pain is getting worse"))
        assert result["risk_level"] == RiskLevel.CRITICAL
        assert result["requires_human_review"] is True

    def test_jaw_pain_triggers_critical(self):
        result = risk_flag(_state(transcript="jaw pain since this morning"))
        assert result["risk_level"] == RiskLevel.CRITICAL

    def test_suicidal_triggers_critical(self):
        result = risk_flag(_state(transcript="I have been feeling suicidal lately"))
        assert result["risk_level"] == RiskLevel.CRITICAL
        assert result["requires_human_review"] is True

    def test_overdose_triggers_critical(self):
        result = risk_flag(_state(transcript="I think I may have taken an overdose"))
        assert result["risk_level"] == RiskLevel.CRITICAL

    def test_cant_breathe_triggers_critical(self):
        result = risk_flag(_state(transcript="I can't breathe properly"))
        assert result["risk_level"] == RiskLevel.CRITICAL

    def test_cannot_breathe_variant(self):
        result = risk_flag(_state(transcript="I cannot breathe at all"))
        assert result["risk_level"] == RiskLevel.CRITICAL

    def test_keyword_match_is_case_insensitive(self):
        # Transcript lowercased internally — test that UPPER case still matches
        result = risk_flag(_state(transcript="CHEST PAIN and ARM PAIN"))
        assert result["risk_level"] == RiskLevel.CRITICAL

    def test_multiple_keywords_all_appear_in_reasons(self):
        result = risk_flag(_state(transcript="chest pain and jaw pain and arm pain"))
        assert result["risk_level"] == RiskLevel.CRITICAL
        reasons_str = " ".join(result["risk_reasons"])
        assert "chest pain" in reasons_str
        assert "jaw pain" in reasons_str
        assert "arm pain" in reasons_str


# ---------------------------------------------------------------------------
# HIGH — extraction failure
# ---------------------------------------------------------------------------

class TestExtractionFailedEscalation:
    def test_extraction_failed_escalates_to_high(self):
        result = risk_flag(_state(extraction_failed=True))
        assert result["risk_level"] == RiskLevel.HIGH
        assert result["requires_human_review"] is True
        assert any("extraction failed" in r.lower() for r in result["risk_reasons"])

    def test_critical_keyword_beats_extraction_failed(self):
        # CRITICAL takes priority even when extraction_failed is True
        result = risk_flag(_state(
            transcript="chest pain",
            extraction_failed=True,
        ))
        assert result["risk_level"] == RiskLevel.CRITICAL


# ---------------------------------------------------------------------------
# HIGH — missed doses + active symptoms
# ---------------------------------------------------------------------------

class TestMissedDosesWithSymptoms:
    def test_missed_doses_and_symptoms_escalates_to_high(self):
        result = risk_flag(_state(
            clinical_signals={
                "missed_doses": True,
                "symptoms": ["headache", "dizziness"],
            }
        ))
        assert result["risk_level"] == RiskLevel.HIGH
        assert result["requires_human_review"] is True

    def test_missed_doses_without_symptoms_stays_low(self):
        result = risk_flag(_state(
            clinical_signals={"missed_doses": True, "symptoms": []}
        ))
        assert result["risk_level"] == RiskLevel.LOW
        assert result["requires_human_review"] is False

    def test_symptoms_without_missed_doses_stays_low(self):
        result = risk_flag(_state(
            clinical_signals={"missed_doses": False, "symptoms": ["fatigue"]}
        ))
        assert result["risk_level"] == RiskLevel.LOW

    def test_critical_keyword_beats_missed_doses_plus_symptoms(self):
        result = risk_flag(_state(
            transcript="chest pain",
            clinical_signals={"missed_doses": True, "symptoms": ["dizziness"]},
        ))
        assert result["risk_level"] == RiskLevel.CRITICAL


# ---------------------------------------------------------------------------
# MEDIUM — glycemic concern without exercise
# ---------------------------------------------------------------------------

class TestGlycemicConcern:
    def test_glycemic_concern_no_exercise_gives_medium(self):
        result = risk_flag(_state(
            meal_data={"glycemic_concern": True},
            clinical_signals={"exercise_reported": False},
        ))
        assert result["risk_level"] == RiskLevel.MEDIUM
        assert result["requires_human_review"] is False

    def test_glycemic_concern_with_exercise_stays_low(self):
        result = risk_flag(_state(
            meal_data={"glycemic_concern": True},
            clinical_signals={"exercise_reported": True},
        ))
        assert result["risk_level"] == RiskLevel.LOW

    def test_no_glycemic_concern_stays_low(self):
        result = risk_flag(_state(
            meal_data={"glycemic_concern": False},
            clinical_signals={"exercise_reported": False},
        ))
        assert result["risk_level"] == RiskLevel.LOW


# ---------------------------------------------------------------------------
# LOW — default / happy path
# ---------------------------------------------------------------------------

class TestLowRiskDefault:
    def test_empty_state_returns_low(self):
        result = risk_flag(_state())
        assert result["risk_level"] == RiskLevel.LOW
        assert result["requires_human_review"] is False
        assert result["risk_reasons"] == ["No risk factors identified"]

    def test_healthy_patient_returns_low(self):
        result = risk_flag(_state(
            transcript="Hi, I took my metformin this morning. Feeling great.",
            clinical_signals={
                "missed_doses": False,
                "symptoms": [],
                "exercise_reported": True,
            },
            meal_data={"glycemic_concern": False},
        ))
        assert result["risk_level"] == RiskLevel.LOW
        assert result["requires_human_review"] is False


# ---------------------------------------------------------------------------
# State output contract
# ---------------------------------------------------------------------------

class TestOutputContract:
    def test_latency_ms_is_immutably_merged(self):
        # Existing latency entries must be preserved
        existing = {"transcribe": 120.0, "extract_signals": 340.0}
        result = risk_flag(_state(latency_ms=existing))
        assert result["latency_ms"]["transcribe"] == 120.0
        assert result["latency_ms"]["extract_signals"] == 340.0
        assert "risk_flag" in result["latency_ms"]
        # Original dict must not be mutated
        assert "risk_flag" not in existing

    def test_output_keys_present(self):
        result = risk_flag(_state())
        assert set(result.keys()) == {
            "risk_level", "risk_reasons", "requires_human_review", "latency_ms"
        }
