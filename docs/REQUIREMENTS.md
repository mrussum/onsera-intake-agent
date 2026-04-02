# Requirements

## 1. Functional requirements

### 1.1 Audio intake

| ID | Requirement | Priority |
|---|---|---|
| FR-01 | The system MUST accept audio recordings in `audio/webm` format submitted via multipart form upload | Must |
| FR-02 | The system MUST accept audio files up to 50 MB | Must |
| FR-03 | The system MUST reject audio files exceeding 50 MB with HTTP 413 | Must |
| FR-04 | The system MUST reject unsupported MIME types with HTTP 415 | Must |
| FR-05 | The system MUST reject empty audio files with HTTP 400 | Must |
| FR-06 | The system MUST accept a `patient_id` string alongside the audio file | Must |
| FR-07 | The system MUST return a `job_id` immediately after upload (async processing) | Must |

### 1.2 Transcription

| ID | Requirement | Priority |
|---|---|---|
| FR-08 | The system MUST transcribe audio using Groq `whisper-large-v3` | Must |
| FR-09 | The system MUST store the raw transcript in pipeline state | Must |
| FR-10 | Transcription errors MUST propagate to job status `error` | Must |

### 1.3 Clinical signal extraction

| ID | Requirement | Priority |
|---|---|---|
| FR-11 | The system MUST extract symptoms, medications, meals, mood, sleep hours, exercise, and concerns from the transcript | Must |
| FR-12 | Extraction MUST use Claude Sonnet via `with_structured_output()` and a Pydantic schema | Must |
| FR-13 | The system MUST set `missed_doses` as a boolean (not a string) | Must |
| FR-14 | Extraction failure MUST set `extraction_failed=True` and escalate to HIGH risk | Must |
| FR-15 | Extraction failure MUST NOT silently default to LOW risk | Must |

### 1.4 Nutritional analysis

| ID | Requirement | Priority |
|---|---|---|
| FR-16 | The system MUST analyse meal nutritional content when meals are mentioned | Must |
| FR-17 | The system MUST skip meal analysis and return safe defaults when no meals are mentioned | Must |
| FR-18 | Nutritional output MUST include: calories, carb load, glycemic concern, saturated fat concern, quality score (1–10), flags, and notes | Must |

### 1.5 Risk stratification

| ID | Requirement | Priority |
|---|---|---|
| FR-19 | Risk stratification MUST be deterministic Python — no LLM involvement | Must |
| FR-20 | The system MUST classify risk as one of: `low`, `medium`, `high`, `critical` | Must |
| FR-21 | The system MUST detect the following critical keywords in the transcript: "chest pain", "can't breathe", "cannot breathe", "difficulty breathing", "severe headache", "vision loss", "arm pain", "jaw pain", "suicidal", "self harm", "self-harm", "overdose" | Must |
| FR-22 | Any critical keyword match MUST result in `risk_level=critical` | Must |
| FR-23 | `missed_doses=True` AND non-empty `symptoms` MUST result in `risk_level=high` | Must |
| FR-24 | `glycemic_concern=True` AND `exercise_reported=False` MUST result in `risk_level=medium` | Should |
| FR-25 | `risk_level=high` or `critical` MUST set `requires_human_review=True` | Must |
| FR-26 | The same transcript MUST always produce the same risk level (determinism) | Must |

### 1.6 Human-in-the-loop

| ID | Requirement | Priority |
|---|---|---|
| FR-27 | HIGH and CRITICAL intakes MUST pause pipeline execution before `generate_summary` | Must |
| FR-28 | Paused jobs MUST be resumable without re-running earlier pipeline nodes | Must |
| FR-29 | The system MUST expose a `POST /intake/{job_id}/approve` endpoint | Must |
| FR-30 | Clinicians MUST be able to attach a note when approving | Should |
| FR-31 | The approval note MUST appear in the final clinical summary | Should |
| FR-32 | Attempting to approve a job that is not `awaiting_review` MUST return HTTP 409 | Must |

### 1.7 Clinical summary generation

| ID | Requirement | Priority |
|---|---|---|
| FR-33 | The system MUST generate a structured markdown summary for every completed intake | Must |
| FR-34 | The summary MUST contain sections: Patient Check-In Summary, Key Findings, Nutritional Assessment, Action Items, Patient Concerns | Must |
| FR-35 | The summary MUST be factual — it MUST NOT introduce information not present in the transcript or extracted signals | Must |
| FR-36 | Summaries for high/critical intakes MUST include a prominent escalation notice | Must |

### 1.8 API

| ID | Requirement | Priority |
|---|---|---|
| FR-37 | The system MUST expose `POST /intake` | Must |
| FR-38 | The system MUST expose `GET /intake/{job_id}` | Must |
| FR-39 | The system MUST expose `POST /intake/{job_id}/approve` | Must |
| FR-40 | The system MUST expose `GET /dashboard` | Must |
| FR-41 | The system MUST expose `GET /health` | Must |
| FR-42 | The dashboard endpoint MUST return intakes sorted: CRITICAL first, then HIGH, MEDIUM, LOW; ties broken by recency (most recent first) | Must |
| FR-43 | The dashboard MUST include intakes with status `complete` and `awaiting_review` | Must |
| FR-44 | The dashboard MUST include a `summary_preview` (first 200 chars of `clinical_summary`) | Should |
| FR-45 | All endpoints MUST allow CORS from `localhost:3000`, `localhost:5173`, `localhost:5174` | Must |

### 1.9 Observability

| ID | Requirement | Priority |
|---|---|---|
| FR-46 | Every pipeline node MUST record its execution time in `latency_ms` | Must |
| FR-47 | Latency data MUST be exposed in `GET /intake/{job_id}` and the detail modal | Must |
| FR-48 | The health endpoint MUST report job counts by status | Should |

### 1.10 Frontend

| ID | Requirement | Priority |
|---|---|---|
| FR-49 | The frontend MUST provide a voice recorder using `MediaRecorder` in `audio/webm` format | Must |
| FR-50 | The frontend MUST poll job status every 2 seconds until terminal state | Must |
| FR-51 | The frontend MUST refresh the dashboard every 10 seconds automatically | Must |
| FR-52 | Risk cards MUST use colour coding: critical=red, high=orange, medium=yellow, low=green | Must |
| FR-53 | The frontend MUST show an "Awaiting Clinician Review" banner on paused cards | Must |
| FR-54 | The detail modal MUST include an approve panel for `awaiting_review` jobs | Must |
| FR-55 | The detail modal MUST display: clinical summary, clinical signals JSON, meal data JSON, latency breakdown, risk reasons | Must |
| FR-56 | The frontend MUST use no external UI libraries — inline styles only | Must |

---

## 2. Non-functional requirements

### 2.1 Performance

| ID | Requirement | Target |
|---|---|---|
| NFR-01 | End-to-end pipeline latency (LOW/MEDIUM cases) | < 30 seconds |
| NFR-02 | Audio upload response time | < 500 ms |
| NFR-03 | Dashboard API response time | < 200 ms |
| NFR-04 | Risk flag node execution time | < 5 ms (pure Python) |
| NFR-05 | Concurrent pipeline executions | ≥ 4 simultaneous |

### 2.2 Reliability

| ID | Requirement | Target |
|---|---|---|
| NFR-06 | Pipeline errors MUST NOT crash the FastAPI server | Always |
| NFR-07 | Failed jobs MUST be stored with `status=error` (not silently dropped) | Always |
| NFR-08 | Audio files MUST be cleaned up after processing (success or failure) | Always |
| NFR-09 | A `NodeInterrupt` MUST NOT lose graph state | Always |

### 2.3 Safety (clinical)

| ID | Requirement | Target |
|---|---|---|
| NFR-10 | The safety gate (`risk_flag`) MUST be LLM-free and deterministic | Always |
| NFR-11 | A CRITICAL case MUST trigger `requires_human_review=True` with probability 1.0 | Always |
| NFR-12 | A HIGH case MUST trigger `requires_human_review=True` with probability 1.0 | Always |
| NFR-13 | The system MUST NOT generate a clinical summary for a HIGH/CRITICAL case without clinician approval | Always |
| NFR-14 | Extraction failure MUST escalate, not suppress | Always |

### 2.4 Security

| ID | Requirement | Target |
|---|---|---|
| NFR-15 | API keys MUST be loaded from environment variables, not hardcoded | Always |
| NFR-16 | `.env` MUST be excluded from version control | Always |
| NFR-17 | Audio files MUST be saved to a system temp directory with a UUID filename | Always |
| NFR-18 | File upload MUST validate MIME type and size before writing to disk | Always |

### 2.5 Maintainability

| ID | Requirement | Target |
|---|---|---|
| NFR-19 | The pipeline MUST be composable — individual nodes MUST be independently testable | Always |
| NFR-20 | JSON extraction MUST use schema-validated structured output (not raw string parsing) | Always |
| NFR-21 | Each node MUST return a new `latency_ms` dict (immutable state pattern) | Always |
| NFR-22 | The risk stratification rules MUST be documented in code and in this requirements document | Always |

### 2.6 Scalability

| ID | Requirement | Target |
|---|---|---|
| NFR-23 | The `ThreadPoolExecutor` worker count MUST be configurable | Should |
| NFR-24 | The `MemorySaver` checkpoint store MUST be swappable for a persistent backend | Should |
| NFR-25 | The `job_store` MUST be swappable for Redis/PostgreSQL | Should |

---

## 3. Constraints

| ID | Constraint | Reason |
|---|---|---|
| CON-01 | Transcription MUST use Groq (not OpenAI Whisper) | Interview specification |
| CON-02 | All LLM calls MUST use Anthropic Claude (not OpenAI GPT) | Interview specification |
| CON-03 | Pipeline orchestration MUST use LangGraph | Interview specification |
| CON-04 | Frontend MUST use React + Vite | Interview specification |
| CON-05 | Backend MUST use FastAPI | Interview specification |
| CON-06 | Safety decisions MUST NOT use an LLM | Clinical AI best practice |
| CON-07 | Frontend MUST NOT use external UI libraries | Interview specification |

---

## 4. Assumptions

| ID | Assumption |
|---|---|
| ASM-01 | Patients are speaking English (Whisper supports multilingual, but prompts are English-only) |
| ASM-02 | Audio recordings are ≤ 5 minutes in length |
| ASM-03 | Patient IDs are provided by an upstream system and trusted as-is |
| ASM-04 | The dashboard is accessed only by authorised clinicians (no auth implemented in this version) |
| ASM-05 | The Groq and Anthropic APIs are available with acceptable latency |
| ASM-06 | The `MemorySaver` checkpoint store survives the lifetime of a single intake session (single process, no restart) |
| ASM-07 | "arm pain" as a standalone term is sufficient to trigger CRITICAL classification in this version (co-occurrence rules deferred) |

---

## 5. Out of scope (v1)

| Item | Notes |
|---|---|
| Authentication / authorisation | All endpoints are open. Add API key or OAuth in production. |
| Persistent storage | `job_store` is in-memory. Data is lost on restart. |
| Streaming summary generation | Summary generation takes 10–15s. SSE streaming is deferred. |
| Audit logging | No log of who approved what or when. |
| Multi-language support | English only in this version. |
| Patient notification | No SMS/email sent to patient after processing. |
| EHR integration | No HL7/FHIR export. |
| Rate limiting | No per-patient or per-IP rate limiting. |
