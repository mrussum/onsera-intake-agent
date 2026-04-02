# Data Models

## 1. AgentState — LangGraph pipeline state

The canonical state object passed between all six pipeline nodes.
Defined as a `TypedDict` in `backend/agents/intake_graph.py`.

| Field | Type | Default | Description |
|---|---|---|---|
| `audio_path` | `str` | required | Absolute path to the saved audio file |
| `patient_id` | `str` | required | Identifier provided by the submitting client |
| `transcript` | `str` | `""` | Raw text from Groq Whisper transcription |
| `clinical_signals` | `dict` | `{}` | Serialised `ClinicalSignals` from extract_signals node |
| `meal_data` | `dict` | `{}` | Serialised `MealAnalysis` from meal_analysis node |
| `risk_level` | `RiskLevel` | `"low"` | Enum: `low` \| `medium` \| `high` \| `critical` |
| `risk_reasons` | `list[str]` | `[]` | Human-readable reasons for the assigned risk level |
| `clinical_summary` | `str` | `""` | Markdown summary from generate_summary node |
| `requires_human_review` | `bool` | `False` | True when risk is HIGH or CRITICAL |
| `human_review_note` | `str` | `""` | Clinician note injected before resumption |
| `extraction_failed` | `bool` | `False` | True when extract_signals structured output fails |
| `latency_ms` | `dict[str, float]` | `{}` | Per-node execution times in milliseconds |
| `messages` | `list[BaseMessage]` | `[]` | LangChain message history (add_messages reducer) |

### RiskLevel enum

```python
class RiskLevel(str, Enum):
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"
```

---

## 2. ClinicalSignals — structured extraction schema

Pydantic model used with `with_structured_output()` in `extract_signals`.

| Field | Type | Default | Description |
|---|---|---|---|
| `symptoms` | `list[str]` | `[]` | Symptoms mentioned by the patient (e.g. `["fatigue", "headache"]`) |
| `medications` | `list[MedicationRecord]` | `[]` | Medications with dose and adherence |
| `meals_mentioned` | `list[str]` | `[]` | Foods/meals described (e.g. `["eggs", "toast", "orange juice"]`) |
| `weight_change` | `str \| null` | `null` | `"gain"`, `"loss"`, `"stable"`, or `null` |
| `exercise_reported` | `bool` | `false` | Whether any exercise was mentioned |
| `mood` | `str \| null` | `null` | Patient's self-reported mood |
| `sleep_hours` | `float \| null` | `null` | Hours of sleep reported |
| `concerns` | `list[str]` | `[]` | Patient concerns or questions |
| `missed_doses` | `bool` | `false` | True if any medication doses were explicitly missed |

### MedicationRecord

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | required | Medication name (e.g. `"metformin"`) |
| `dose` | `str` | `""` | Dose string (e.g. `"500mg"`) |
| `adherent` | `bool` | `true` | Whether patient took this medication as prescribed |

### Example

```json
{
  "symptoms": ["fatigue", "mild headache"],
  "medications": [
    { "name": "metformin", "dose": "500mg", "adherent": true },
    { "name": "lisinopril", "dose": "10mg", "adherent": false }
  ],
  "meals_mentioned": ["eggs", "toast", "orange juice", "chicken salad"],
  "weight_change": "stable",
  "exercise_reported": false,
  "mood": "tired but okay",
  "sleep_hours": 6.5,
  "concerns": ["feeling more tired than usual"],
  "missed_doses": true
}
```

---

## 3. MealAnalysis — nutritional analysis schema

Pydantic model used with `with_structured_output()` in `meal_analysis`.

| Field | Type | Constraints | Description |
|---|---|---|---|
| `estimated_calories` | `int \| null` | `null` if unknown | Approximate total daily calorie intake |
| `carb_load` | `str` | `"low"` \| `"moderate"` \| `"high"` | Overall carbohydrate load |
| `saturated_fat_concern` | `bool` | — | True if saturated fat intake is clinically concerning |
| `glycemic_concern` | `bool` | — | True if glycemic load is concerning for a diabetic patient |
| `meal_quality_score` | `int` | `1–10` | Overall meal quality (1=very poor, 10=excellent) |
| `flags` | `list[str]` | — | Specific dietary flags (e.g. `["high sugar intake", "no vegetables"]`) |
| `notes` | `str` | — | Brief clinical note on nutritional findings |

### Example

```json
{
  "estimated_calories": 1650,
  "carb_load": "high",
  "saturated_fat_concern": false,
  "glycemic_concern": true,
  "meal_quality_score": 4,
  "flags": ["high glycemic index foods", "insufficient fibre", "sugary drink at breakfast"],
  "notes": "Patient's breakfast (eggs, toast, orange juice) has moderate-high glycaemic load. Orange juice contributes significant free sugars. No vegetables reported. Recommend replacing OJ with water and adding vegetables to at least one meal."
}
```

### When no meals are reported

```json
{
  "estimated_calories": null,
  "carb_load": null,
  "saturated_fat_concern": false,
  "glycemic_concern": false,
  "meal_quality_score": null,
  "flags": [],
  "notes": "No meals reported by patient."
}
```

---

## 4. Job record — `job_store` shape

The in-memory dictionary stored per job. Shape depends on job status.

### While processing

```json
{
  "job_id": "a3f8c2d1-7e4b-4a1c-9f0e-123456789abc",
  "status": "processing",
  "created_at": "2026-04-02T10:15:00+00:00",
  "patient_id": "P1001",
  "latency_ms": { "transcribe": 1820.4, "extract_signals": 3412.7 }
}
```

### Awaiting review (paused by NodeInterrupt)

```json
{
  "job_id": "a3f8c2d1-...",
  "status": "awaiting_review",
  "created_at": "2026-04-02T10:15:00+00:00",
  "paused_at": "2026-04-02T10:15:22+00:00",
  "patient_id": "P3007",
  "transcript": "I've been having chest pain...",
  "clinical_signals": { "symptoms": ["chest pain", "arm pain"], "missed_doses": true, "...": "..." },
  "meal_data": { "notes": "No meals reported by patient.", "..." : "..." },
  "risk_level": "critical",
  "risk_reasons": ["Critical keyword detected: 'chest pain'", "Critical keyword detected: 'arm pain'"],
  "requires_human_review": true,
  "human_review_note": "⚠️ ESCALATED FOR HUMAN REVIEW — Risk: CRITICAL...",
  "clinical_summary": "",
  "latency_ms": { "transcribe": 1820.4, "extract_signals": 3412.7, "meal_analysis": 0.0, "risk_flag": 0.02, "human_review_gate": 0.18 }
}
```

### Complete

```json
{
  "job_id": "a3f8c2d1-...",
  "status": "complete",
  "created_at": "2026-04-02T10:15:00+00:00",
  "completed_at": "2026-04-02T10:15:38+00:00",
  "total_ms": 23450.12,
  "patient_id": "P1001",
  "transcript": "Hi, I'm Sarah...",
  "clinical_signals": { "...": "..." },
  "meal_data": { "...": "..." },
  "risk_level": "medium",
  "risk_reasons": ["Glycemic concern with no exercise reported"],
  "clinical_summary": "## Patient Check-In Summary\n...",
  "requires_human_review": false,
  "human_review_note": "",
  "latency_ms": {
    "transcribe": 1820.4,
    "extract_signals": 3412.7,
    "meal_analysis": 4102.3,
    "risk_flag": 0.02,
    "generate_summary": 11890.1
  }
}
```

### Error

```json
{
  "job_id": "a3f8c2d1-...",
  "status": "error",
  "created_at": "2026-04-02T10:15:00+00:00",
  "completed_at": "2026-04-02T10:15:05+00:00",
  "error": "Pipeline execution failed — see server logs."
}
```

---

## 5. Dashboard response item

The `GET /dashboard` endpoint returns an array of job records augmented with:

| Additional field | Type | Description |
|---|---|---|
| `summary_preview` | `str` | First 200 characters of `clinical_summary` (empty string if not yet generated) |

---

## 6. Evaluation — GoldenCase

Used in `backend/evaluation/ragas_harness.py`.

| Field | Type | Description |
|---|---|---|
| `case_id` | `str` | Unique identifier (e.g. `"gc_001"`) |
| `description` | `str` | Human-readable description of the test scenario |
| `transcript` | `str` | The mock patient transcript |
| `expected_signals` | `dict` | Subset of `ClinicalSignals` fields to assert against |
| `expected_risk` | `str` | Expected `risk_level` value |
| `must_flag_review` | `bool` | Whether `requires_human_review` must be True |

### Example

```python
GoldenCase(
    case_id="gc_003",
    description="CRITICAL: chest pain and missed medication",
    transcript="I've been having chest pain since this morning, arm pain too...",
    expected_signals={
        "missed_doses": True,
        "symptoms": ["chest pain", "arm pain", "jaw pain"],
        "exercise_reported": False,
    },
    expected_risk="critical",
    must_flag_review=True,
)
```

---

## 7. Scoring model — RAGAS harness

### score_extraction(predicted, expected) → float [0.0–1.0]

Field-level coverage between predicted and expected signals.

| Value type | Scoring rule |
|---|---|
| `bool` | 1.0 if exact match, 0.0 otherwise |
| `list[str]` | `len(intersection) / len(expected)` |
| `list[dict]` | Intersection by `name` field / `len(expected)` |
| `int \| float` | 1.0 if within 20% of expected, 0.5 otherwise |
| `str` | 1.0 if case-insensitive match, 0.0 otherwise |
| Key missing | 0.0 |

### score_safety(predicted_risk, predicted_review, expected_risk, should_review) → float [0.0–1.0]

Asymmetric safety scoring — penalises false negatives more heavily than false positives.

| Condition | Score | Rationale |
|---|---|---|
| CRITICAL not flagged for review | **0.0** | Catastrophic failure |
| HIGH not flagged for review | **0.0** | Catastrophic failure |
| Perfect match (risk + review) | **1.0** | — |
| Correct review decision, wrong risk level | **0.8** | Clinician still notified |
| Over-detection (low-risk flagged) | **0.7** | False positive — safe but inefficient |
| Under-detection (non-critical not flagged) | **0.3** | Concerning but not catastrophic |
