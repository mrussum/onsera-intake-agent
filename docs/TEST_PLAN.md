# Test Plan

## 1. Test strategy

### Scope

This plan covers the Onsera Intake Agent backend pipeline, API layer, and
evaluation harness. Frontend testing is manual (no automated browser tests
in v1).

### Test levels

| Level | Tool | Location | When to run |
|---|---|---|---|
| Unit | Python `assert` / `unittest.mock` | `test_pipeline.py` | Every code change |
| Integration | Live API calls (Anthropic + Groq) | `test_pipeline.py` | Pre-merge, pre-deploy |
| Safety gate | Deterministic assertions | `test_pipeline.py` | Every code change |
| Evaluation | `ragas_harness.py` golden dataset | `evaluation/ragas_harness.py` | Weekly / model change |
| Manual | Browser | Localhost | After any frontend change |

### Safety-first principle

Any test that verifies a safety property (CRITICAL cases must be flagged,
extraction failure must escalate) is treated as a **hard gate** — a failure
blocks deployment regardless of other passing tests.

---

## 2. Unit test cases

These tests run without API calls. They verify deterministic logic.

### 2.1 risk_flag node

| TC-ID | Test | Input | Expected | Priority |
|---|---|---|---|---|
| UT-01 | CRITICAL: single keyword | transcript contains "chest pain" | `risk_level=critical`, `requires_human_review=True` | Critical |
| UT-02 | CRITICAL: keyword at end of string | transcript ends with "…jaw pain" | `risk_level=critical` | Critical |
| UT-03 | CRITICAL: keyword case-insensitive | transcript contains "CHEST PAIN" | `risk_level=critical` | Critical |
| UT-04 | CRITICAL: multiple keywords | transcript contains "chest pain" and "overdose" | `risk_level=critical`, both reasons recorded | High |
| UT-05 | HIGH: missed doses + symptoms | `missed_doses=True`, `symptoms=["fatigue"]` | `risk_level=high`, `requires_human_review=True` | Critical |
| UT-06 | HIGH: missed doses, no symptoms | `missed_doses=True`, `symptoms=[]` | `risk_level=low` (rule not triggered) | High |
| UT-07 | HIGH: symptoms, no missed doses | `missed_doses=False`, `symptoms=["nausea"]` | `risk_level=low` | High |
| UT-08 | HIGH: extraction_failed | `extraction_failed=True`, no keywords | `risk_level=high`, `requires_human_review=True` | Critical |
| UT-09 | MEDIUM: glycemic + no exercise | `glycemic_concern=True`, `exercise_reported=False` | `risk_level=medium`, `requires_human_review=False` | Medium |
| UT-10 | MEDIUM: glycemic + exercise | `glycemic_concern=True`, `exercise_reported=True` | `risk_level=low` | Medium |
| UT-11 | LOW: default | no keywords, no missed doses, no glycemic | `risk_level=low`, `requires_human_review=False` | High |
| UT-12 | CRITICAL overrides HIGH | critical keyword + `missed_doses=True` + symptoms | `risk_level=critical` (not HIGH) | Critical |
| UT-13 | Priority: HIGH over MEDIUM | `extraction_failed=True` + `glycemic_concern=True` | `risk_level=high` (not MEDIUM) | High |
| UT-14 | Latency recorded | any state | `latency_ms["risk_flag"]` is set | Medium |
| UT-15 | Latency immutable merge | prior `latency_ms` has "transcribe" key | result retains "transcribe" key | Medium |
| UT-16 | reason: "No risk factors identified" | clean state | `risk_reasons = ["No risk factors identified"]` | Low |

### 2.2 score_safety (ragas harness)

| TC-ID | Test | Input | Expected | Priority |
|---|---|---|---|---|
| UT-17 | Catastrophic: critical not flagged | predicted=critical, review=False, expected=critical, should=True | `0.0` | Critical |
| UT-18 | Catastrophic: high not flagged | predicted=high, review=False, expected=high, should=True | `0.0` | Critical |
| UT-19 | Perfect match | predicted=critical, review=True, expected=critical, should=True | `1.0` | High |
| UT-20 | Correct review, wrong level | predicted=high, review=True, expected=critical, should=True | `0.8` | Medium |
| UT-21 | Over-detection | predicted=low, review=True, expected=low, should=False | `0.7` | Medium |
| UT-22 | Under-detection (non-critical) | predicted=medium, review=False, expected=high, should=True | `0.0` | Critical |

### 2.3 score_extraction (ragas harness)

| TC-ID | Test | Input | Expected | Priority |
|---|---|---|---|---|
| UT-23 | Empty expected | `expected={}` | `1.0` | Low |
| UT-24 | Bool match | `predicted={"missed_doses": True}`, `expected={"missed_doses": True}` | `1.0` | High |
| UT-25 | Bool mismatch | `predicted={"missed_doses": False}`, `expected={"missed_doses": True}` | `0.0` | High |
| UT-26 | List full overlap | predicted symptoms contain all expected | `1.0` | High |
| UT-27 | List partial overlap | predicted contains 1 of 2 expected symptoms | `0.5` | Medium |
| UT-28 | List no overlap | no predicted symptoms match expected | `0.0` | Medium |
| UT-29 | Missing key | expected key absent from predicted | `0.0` contribution for that field | Medium |
| UT-30 | Numeric within 20% | predicted=8.0, expected=8.0 | `1.0` | Low |
| UT-31 | Numeric outside 20% | predicted=5.0, expected=8.0 | `0.5` | Low |

---

## 3. Integration test cases

These tests make live API calls to Anthropic and Groq. The transcription node
is mocked (no audio file needed).

| TC-ID | Scenario | Transcript summary | Assertions | Priority |
|---|---|---|---|---|
| IT-01 | Normal intake | metformin, eggs/toast, tired | `requires_human_review=False` | Critical |
| IT-02 | Critical: chest pain | chest pain, arm pain, jaw pain, missed meds | `requires_human_review=True`, `risk_level=critical` | Critical |
| IT-03 | High: missed doses + symptoms | missed lisinopril, headache, dizziness | `requires_human_review=True`, `risk_level=high` | Critical |
| IT-04 | Medium: glycemic, no exercise | high-sugar meals, no exercise | `risk_level=medium`, `requires_human_review=False` | High |
| IT-05 | No meals mentioned | no food mentioned | `meal_data.notes = "No meals reported by patient."` | Medium |
| IT-06 | Exercise reported | morning run, healthy meals | `exercise_reported=True` | Medium |
| IT-07 | Clinical signals extracted | full check-in | `clinical_signals.missed_doses` is bool, `symptoms` is list | High |
| IT-08 | Latency populated | any transcript | All pipeline nodes have entries in `latency_ms` | Medium |
| IT-09 | NodeInterrupt fires | critical keyword | `GraphInterrupt` raised; graph state checkpointed | Critical |
| IT-10 | Resume after interrupt | critical case, then mock approve | `generate_summary` runs; `clinical_summary` non-empty | Critical |

### Running integration tests

```bash
# From repo root (requires .env with valid API keys)
python test_pipeline.py
```

---

## 4. API-level test cases

These test the FastAPI layer without requiring a running pipeline.

| TC-ID | Endpoint | Test | Expected | Priority |
|---|---|---|---|---|
| AT-01 | `GET /health` | Server is running | `status=ok` | High |
| AT-02 | `POST /intake` | Valid webm + patient_id | `job_id` returned, `status=processing` | Critical |
| AT-03 | `POST /intake` | Missing `patient_id` | 422 Unprocessable Entity | High |
| AT-04 | `POST /intake` | Missing `audio` | 422 Unprocessable Entity | High |
| AT-05 | `POST /intake` | Empty audio file | 400 Bad Request | High |
| AT-06 | `POST /intake` | File > 50 MB | 413 Request Entity Too Large | High |
| AT-07 | `POST /intake` | Unsupported MIME `video/mp4` | 415 Unsupported Media Type | Medium |
| AT-08 | `GET /intake/{job_id}` | Valid job_id | Job record returned | Critical |
| AT-09 | `GET /intake/{job_id}` | Unknown job_id | 404 Not Found | High |
| AT-10 | `POST /approve` | Job in `awaiting_review` | `status=processing` in response | Critical |
| AT-11 | `POST /approve` | Job in `complete` state | 409 Conflict | High |
| AT-12 | `POST /approve` | Unknown job_id | 404 Not Found | High |
| AT-13 | `GET /dashboard` | Mixed statuses | Only `complete` + `awaiting_review` returned | High |
| AT-14 | `GET /dashboard` | Mixed risk levels | `critical` items appear before `low` | High |
| AT-15 | `GET /dashboard` | CORS header | `Access-Control-Allow-Origin` present | Medium |

---

## 5. Safety gate test cases

These are hard-pass/hard-fail tests that block deployment if they fail.

| TC-ID | Test | Method | Pass criterion |
|---|---|---|---|
| SG-01 | CRITICAL keyword → human review | Unit | `score_safety(...) > 0.0` for all CRITICAL golden cases |
| SG-02 | HIGH risk (missed doses + symptoms) → human review | Unit | `score_safety(...) > 0.0` for all HIGH golden cases |
| SG-03 | Extraction failure → human review | Unit | `extraction_failed=True` → `risk_level=high`, `requires_human_review=True` |
| SG-04 | risk_flag contains no LLM calls | Code review | `risk_flag()` function makes no network calls |
| SG-05 | Same transcript → same risk level | Unit (determinism) | Running `risk_flag` 10× with identical state produces identical output |
| SG-06 | Critical summary not generated without approval | Integration | `clinical_summary=""` in `awaiting_review` job record |

---

## 6. Evaluation harness test cases

Run against the golden dataset in `backend/evaluation/ragas_harness.py`.

| Case | Risk | `must_flag_review` | Minimum safety score | Minimum extraction score |
|---|---|---|---|---|
| gc_001 (routine low-risk) | low | False | 0.7 | 0.6 |
| gc_002 (HIGH: missed meds + symptoms) | high | True | **1.0** (catastrophic gate) | 0.5 |
| gc_003 (CRITICAL: chest pain) | critical | True | **1.0** (catastrophic gate) | 0.5 |

**CI gate:** If any case with `must_flag_review=True` returns `safety_score=0.0`,
the build is failed. This is a zero-tolerance policy.

### Running the evaluation

```bash
cd backend
python -m evaluation.ragas_harness
```

---

## 7. Manual test cases — frontend

| TC-ID | Test | Steps | Expected |
|---|---|---|---|
| MT-01 | Voice recorder — grant permission | Click Start Recording, grant mic access | Recording starts; pulsing red dot visible |
| MT-02 | Voice recorder — deny permission | Click Start Recording, deny mic access | Alert shown with error message |
| MT-03 | Submit without patient ID | Record audio, leave ID blank, click Submit | Alert: "Please enter a patient ID" |
| MT-04 | Submit without recording | Enter patient ID, click Submit | Alert: "Please record audio first" |
| MT-05 | Status updates during processing | Submit valid recording | Status box updates through node names |
| MT-06 | LOW risk card colour | Submit low-risk transcript | Card has green border and background |
| MT-07 | CRITICAL risk card colour | Submit critical transcript | Card has red border and "Awaiting Review" banner |
| MT-08 | Dashboard auto-refresh | Wait 10 seconds | Dashboard silently reloads |
| MT-09 | Detail modal — complete intake | Click a completed card | Modal shows summary, JSON sections, latency chips |
| MT-10 | Detail modal — awaiting_review | Click an awaiting card | Approve panel visible; summary section says "Awaiting approval" |
| MT-11 | Approve flow | Click Approve in modal | Button shows "Resuming pipeline…"; summary appears after ~15s |
| MT-12 | Header badge counts | Have 2 CRITICAL + 1 awaiting | "2 CRITICAL" and "1 awaiting review" badges in header |
| MT-13 | Modal closes on backdrop click | Click outside modal | Modal closes |
| MT-14 | Re-record | Click Re-record after first recording | New audio replaces old; playback widget updates |
| MT-15 | Safari fallback | Open in Safari | Informative error if webm unsupported; dashboard still readable |

---

## 8. Regression test checklist

Run this after any code change before committing:

```
[ ] python test_pipeline.py — all tests pass
[ ] Import check: python -c "from agents.intake_graph import graph, checkpointer"
[ ] Import check: python -c "from api.main import app"
[ ] risk_flag unit tests pass (no LLM, runs instantly)
[ ] score_safety(critical, False, critical, True) == 0.0
[ ] score_safety(critical, True,  critical, True) == 1.0
[ ] API /health returns 200
[ ] No .env committed (git status shows .env as untracked)
```

---

## 9. Performance benchmarks

Expected timings on a standard API connection (not under load):

| Node | Typical | Acceptable maximum |
|---|---|---|
| `transcribe` | 1–3 s | 10 s |
| `extract_signals` | 2–5 s | 15 s |
| `meal_analysis` | 2–5 s | 15 s |
| `meal_analysis` (skip) | < 1 ms | 5 ms |
| `risk_flag` | < 1 ms | 5 ms |
| `human_review_gate` | < 1 ms | 5 ms |
| `generate_summary` | 8–15 s | 30 s |
| **End-to-end (LOW/MEDIUM)** | **15–25 s** | **60 s** |
| **End-to-end (paused)** | **5–8 s to pause** | **20 s to pause** |
