# API Specification

Base URL: `http://localhost:8000`  
Interactive docs: `http://localhost:8000/docs` (Swagger UI)

---

## POST /intake

Submit a voice recording for processing.

### Request

**Content-Type:** `multipart/form-data`

| Field | Type | Required | Description |
|---|---|---|---|
| `audio` | file | Yes | Audio recording. Accepted: `audio/webm`, `audio/ogg`, `audio/wav`, `audio/mp4`, `audio/mpeg`. Max 50 MB. |
| `patient_id` | string | Yes | Patient identifier string |

### Response — 200 OK

```json
{
  "job_id": "a3f8c2d1-7e4b-4a1c-9f0e-123456789abc",
  "status": "processing"
}
```

### Error responses

| Status | Condition | Body |
|---|---|---|
| 400 | Audio file is empty | `{"detail": "Audio file is empty."}` |
| 413 | File exceeds 50 MB | `{"detail": "Audio file too large (52000KB). Max 50MB."}` |
| 415 | Unsupported MIME type | `{"detail": "Unsupported audio type 'video/mp4'. Accepted: ..."}` |
| 422 | Missing `patient_id` or `audio` field | FastAPI validation error |

### curl example

```bash
curl -X POST http://localhost:8000/intake \
  -F "audio=@/path/to/recording.webm" \
  -F "patient_id=P1001"
```

---

## GET /intake/{job_id}

Poll for job status and results.

### Path parameters

| Parameter | Type | Description |
|---|---|---|
| `job_id` | string (UUID) | Job ID returned by `POST /intake` |

### Response — 200 OK

The response shape varies by `status`.

#### status: processing

```json
{
  "job_id": "a3f8c2d1-...",
  "status": "processing",
  "created_at": "2026-04-02T10:15:00+00:00",
  "patient_id": "P1001",
  "latency_ms": {
    "transcribe": 1820.4,
    "extract_signals": 3412.7
  }
}
```

#### status: awaiting_review

```json
{
  "job_id": "a3f8c2d1-...",
  "status": "awaiting_review",
  "created_at": "2026-04-02T10:15:00+00:00",
  "paused_at": "2026-04-02T10:15:22+00:00",
  "patient_id": "P3007",
  "transcript": "I've been having chest pain...",
  "clinical_signals": { "...": "..." },
  "meal_data": { "...": "..." },
  "risk_level": "critical",
  "risk_reasons": ["Critical keyword detected: 'chest pain'"],
  "requires_human_review": true,
  "human_review_note": "⚠️ ESCALATED FOR HUMAN REVIEW...",
  "clinical_summary": "",
  "latency_ms": { "transcribe": 1820.4, "...": "..." }
}
```

#### status: complete

```json
{
  "job_id": "a3f8c2d1-...",
  "status": "complete",
  "created_at": "2026-04-02T10:15:00+00:00",
  "completed_at": "2026-04-02T10:15:38+00:00",
  "total_ms": 23450.12,
  "patient_id": "P1001",
  "transcript": "Hi, I'm Sarah...",
  "clinical_signals": {
    "symptoms": ["fatigue"],
    "medications": [{ "name": "metformin", "dose": "500mg", "adherent": true }],
    "meals_mentioned": ["eggs", "toast"],
    "weight_change": "stable",
    "exercise_reported": false,
    "mood": "tired",
    "sleep_hours": 7.0,
    "concerns": [],
    "missed_doses": false
  },
  "meal_data": {
    "estimated_calories": 650,
    "carb_load": "moderate",
    "saturated_fat_concern": false,
    "glycemic_concern": true,
    "meal_quality_score": 5,
    "flags": ["high glycemic index breakfast"],
    "notes": "..."
  },
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

#### status: error

```json
{
  "job_id": "a3f8c2d1-...",
  "status": "error",
  "created_at": "2026-04-02T10:15:00+00:00",
  "completed_at": "2026-04-02T10:15:05+00:00",
  "error": "Pipeline execution failed — see server logs."
}
```

### Error responses

| Status | Condition | Body |
|---|---|---|
| 404 | `job_id` not found | `{"detail": "Job abc123 not found"}` |

### curl example

```bash
curl http://localhost:8000/intake/a3f8c2d1-7e4b-4a1c-9f0e-123456789abc
```

---

## POST /intake/{job_id}/approve

Resume a paused pipeline after clinician review.

### Path parameters

| Parameter | Type | Description |
|---|---|---|
| `job_id` | string (UUID) | Job ID of a job with `status=awaiting_review` |

### Request

**Content-Type:** `multipart/form-data`

| Field | Type | Required | Description |
|---|---|---|---|
| `clinician_note` | string | No | Clinician note to include in the summary. Defaults to `"Approved by clinician."` |

### Response — 200 OK

```json
{
  "job_id": "a3f8c2d1-...",
  "status": "processing",
  "message": "Resuming pipeline after clinician approval."
}
```

### Error responses

| Status | Condition | Body |
|---|---|---|
| 404 | `job_id` not found | `{"detail": "Job abc123 not found"}` |
| 409 | Job is not in `awaiting_review` state | `{"detail": "Job abc123 is not awaiting review (status: complete)"}` |

### curl example

```bash
curl -X POST http://localhost:8000/intake/a3f8c2d1-7e4b-4a1c-9f0e-123456789abc/approve \
  -F "clinician_note=Contacted patient — directed to emergency department"
```

---

## GET /dashboard

All visible intakes sorted by risk level then recency.

### Response — 200 OK

Array of job objects. Each item is a complete job record (same shape as
`GET /intake/{job_id}`) with one additional field:

| Field | Type | Description |
|---|---|---|
| `summary_preview` | `string` | First 200 characters of `clinical_summary`. Empty string if not yet generated. |

**Only intakes with `status=complete` or `status=awaiting_review` are included.**

**Sort order:**
1. Risk level: `critical` → `high` → `medium` → `low`
2. Recency: most recent `completed_at` or `paused_at` first

### Example

```json
[
  {
    "job_id": "b1c2d3...",
    "status": "awaiting_review",
    "risk_level": "critical",
    "patient_id": "P3007",
    "paused_at": "2026-04-02T10:20:00+00:00",
    "summary_preview": "",
    "requires_human_review": true,
    "...": "..."
  },
  {
    "job_id": "a3f8c2...",
    "status": "complete",
    "risk_level": "medium",
    "patient_id": "P1001",
    "completed_at": "2026-04-02T10:15:38+00:00",
    "summary_preview": "## Patient Check-In Summary\nPatient P1001 reported...",
    "requires_human_review": false,
    "...": "..."
  }
]
```

### curl example

```bash
curl http://localhost:8000/dashboard | python3 -m json.tool
```

---

## GET /health

Service health check.

### Response — 200 OK

```json
{
  "status": "ok",
  "job_count": 12,
  "by_status": {
    "processing": 1,
    "awaiting_review": 2,
    "complete": 8,
    "error": 1
  }
}
```

### curl example

```bash
curl http://localhost:8000/health
```

---

## Error format

All errors follow FastAPI's standard format:

```json
{
  "detail": "Human-readable error message"
}
```

---

## Job status state machine

```
processing ──▶ awaiting_review ──▶ processing ──▶ complete
           │                                   │
           └──────────────────────────────────▶┤
           │                                   │
           └──────────────────────────────────▶ error
```

| Status | Terminal? | Visible on dashboard? |
|---|---|---|
| `processing` | No | No |
| `awaiting_review` | No (resumable) | Yes |
| `complete` | Yes | Yes |
| `error` | Yes | No |

---

## CORS policy

The following origins are permitted:

```
http://localhost:3000
http://localhost:5173
http://localhost:5174
```

All methods and headers are allowed. Credentials are permitted.

---

## Polling guidance

| Scenario | Recommended interval |
|---|---|
| Waiting for a submitted job | Every 2 seconds |
| Dashboard auto-refresh | Every 10 seconds |
| Waiting after approval | Every 2 seconds until `complete` or `error` |

A job will remain `processing` for approximately 15–25 seconds for a typical
intake. HIGH/CRITICAL cases pause before this and remain `awaiting_review`
until approved.
