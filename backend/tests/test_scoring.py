"""
Unit tests for the RAGAS-inspired scoring functions.

score_extraction() and score_safety() are pure Python with no LLM or I/O
dependency, so these tests run without API keys.
"""

import pytest
from evaluation.ragas_harness import score_extraction, score_safety


# ---------------------------------------------------------------------------
# score_extraction
# ---------------------------------------------------------------------------

class TestScoreExtraction:
    def test_perfect_match_returns_one(self):
        expected = {"missed_doses": True, "exercise_reported": False}
        predicted = {"missed_doses": True, "exercise_reported": False}
        assert score_extraction(predicted, expected) == 1.0

    def test_empty_expected_returns_one(self):
        assert score_extraction({"anything": "x"}, {}) == 1.0

    def test_missing_key_scores_zero_for_that_field(self):
        expected = {"missed_doses": True, "exercise_reported": False}
        predicted = {"missed_doses": True}  # exercise_reported missing
        score = score_extraction(predicted, expected)
        assert score == 0.5  # 1 out of 2 fields

    def test_bool_wrong_value_scores_zero(self):
        expected = {"missed_doses": True}
        predicted = {"missed_doses": False}
        assert score_extraction(predicted, expected) == 0.0

    def test_bool_correct_value_scores_one(self):
        expected = {"missed_doses": False}
        predicted = {"missed_doses": False}
        assert score_extraction(predicted, expected) == 1.0

    def test_list_full_overlap_scores_one(self):
        expected = {"symptoms": ["headache", "dizziness"]}
        predicted = {"symptoms": ["headache", "dizziness"]}
        assert score_extraction(predicted, expected) == 1.0

    def test_list_partial_overlap_scores_fraction(self):
        expected = {"symptoms": ["headache", "dizziness", "nausea"]}
        predicted = {"symptoms": ["headache", "dizziness"]}
        score = score_extraction(predicted, expected)
        assert round(score, 4) == round(2 / 3, 4)

    def test_list_no_overlap_scores_zero(self):
        expected = {"symptoms": ["chest pain"]}
        predicted = {"symptoms": ["fatigue"]}
        assert score_extraction(predicted, expected) == 0.0

    def test_empty_list_expected_scores_one(self):
        expected = {"symptoms": []}
        predicted = {"symptoms": []}
        assert score_extraction(predicted, expected) == 1.0

    def test_list_of_dicts_matched_by_name(self):
        expected = {"medications": [{"name": "metformin", "dose": "500mg"}]}
        predicted = {"medications": [{"name": "metformin", "dose": "500mg", "adherent": True}]}
        assert score_extraction(predicted, expected) == 1.0

    def test_list_of_dicts_wrong_name_scores_zero(self):
        expected = {"medications": [{"name": "metformin"}]}
        predicted = {"medications": [{"name": "lisinopril"}]}
        assert score_extraction(predicted, expected) == 0.0

    def test_numeric_within_20_percent_scores_one(self):
        expected = {"sleep_hours": 8.0}
        predicted = {"sleep_hours": 8.5}  # 6.25% off
        assert score_extraction(predicted, expected) == 1.0

    def test_numeric_outside_20_percent_scores_half(self):
        expected = {"sleep_hours": 8.0}
        predicted = {"sleep_hours": 5.0}  # 37.5% off
        assert score_extraction(predicted, expected) == 0.5

    def test_numeric_non_numeric_prediction_scores_zero(self):
        expected = {"sleep_hours": 8.0}
        predicted = {"sleep_hours": "eight"}
        assert score_extraction(predicted, expected) == 0.0

    def test_string_case_insensitive_match(self):
        expected = {"risk": "high"}
        predicted = {"risk": "HIGH"}
        assert score_extraction(predicted, expected) == 1.0

    def test_string_mismatch_scores_zero(self):
        expected = {"risk": "high"}
        predicted = {"risk": "low"}
        assert score_extraction(predicted, expected) == 0.0

    def test_multiple_fields_averaged(self):
        expected = {
            "missed_doses": True,    # correct → 1.0
            "exercise_reported": True,  # wrong → 0.0
            "sleep_hours": 7.0,       # exact → 1.0
        }
        predicted = {
            "missed_doses": True,
            "exercise_reported": False,
            "sleep_hours": 7.0,
        }
        score = score_extraction(predicted, expected)
        assert round(score, 4) == round(2 / 3, 4)


# ---------------------------------------------------------------------------
# score_safety
# ---------------------------------------------------------------------------

class TestScoreSafety:
    # Perfect matches
    def test_perfect_low_risk_match(self):
        assert score_safety("low", False, "low", False) == 1.0

    def test_perfect_high_risk_match(self):
        assert score_safety("high", True, "high", True) == 1.0

    def test_perfect_critical_match(self):
        assert score_safety("critical", True, "critical", True) == 1.0

    # Catastrophic failures (false negatives on safety-critical cases)
    def test_critical_not_flagged_is_zero(self):
        assert score_safety("low", False, "critical", True) == 0.0

    def test_critical_flagged_wrong_level_not_zero(self):
        # Flagged for review but called it 'high' instead of 'critical'
        score = score_safety("high", True, "critical", True)
        assert score > 0.0  # Not a catastrophic failure — review was triggered

    def test_high_not_flagged_is_zero(self):
        assert score_safety("low", False, "high", True) == 0.0

    # Over-detection (false positives — safer than false negatives)
    def test_low_risk_over_flagged_gives_0_7(self):
        assert score_safety("low", True, "low", False) == 0.7

    def test_medium_risk_over_flagged_gives_0_7(self):
        assert score_safety("medium", True, "medium", False) == 0.7

    # Correct review flag, wrong risk level → 0.8
    def test_correct_review_wrong_level_gives_0_8(self):
        assert score_safety("high", True, "critical", True) == 0.8

    def test_correct_no_review_wrong_level_gives_0_8(self):
        assert score_safety("medium", False, "low", False) == 0.8

    # Under-detection (non-catastrophic — case was expected to be flagged but wasn't)
    def test_missed_high_flag_on_medium_gives_0_3(self):
        # medium case expected to be flagged (must_flag_review=True) but wasn't
        score = score_safety("low", False, "medium", True)
        assert score == 0.3
