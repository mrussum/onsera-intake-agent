# Use Cases

## Actors

| Actor | Description |
|---|---|
| **Patient** | Individual enrolled in remote care. Records voice check-ins via mobile browser. Has no direct access to the dashboard. |
| **Clinician** | Licensed healthcare professional (GP, nurse practitioner, care coordinator). Reviews risk-flagged intakes and approves paused pipelines. |
| **System** | The Onsera Intake Agent — automated pipeline nodes. Acts autonomously between patient submission and clinician review. |
| **Administrator** | Configures the system (API keys, model selection, CORS origins). Not represented in the UI. |

---

## Use case diagram

```
                        ┌─────────────────────────────────────┐
                        │       Onsera Intake Agent           │
                        │                                     │
  ┌─────────┐           │  ┌──────────────────────────────┐   │
  │         │──UC-01────│─▶│ Submit voice check-in        │   │
  │         │           │  └──────────────────────────────┘   │
  │ Patient │──UC-02────│─▶│ Monitor submission status    │   │
  │         │           │  └──────────────────────────────┘   │
  └─────────┘           │                                     │
                        │  ┌──────────────────────────────┐   │
  ┌──────────┐          │  │ View intake dashboard        │◀──│──UC-03──┐
  │          │──UC-04───│─▶│ Review flagged intake        │   │         │
  │Clinician │──UC-05───│─▶│ Approve paused pipeline      │   │         │
  │          │──UC-06───│─▶│ View clinical summary        │   │      ┌──┴──────┐
  └──────────┘          │  └──────────────────────────────┘   │      │Clinician│
                        │                                     │      └─────────┘
  ┌─────────┐           │  ┌──────────────────────────────┐   │
  │         │──UC-07────│─▶│ Transcribe audio             │   │
  │         │──UC-08────│─▶│ Extract clinical signals     │   │
  │ System  │──UC-09────│─▶│ Analyse nutritional content  │   │
  │         │──UC-10────│─▶│ Risk-stratify patient        │   │
  │         │──UC-11────│─▶│ Generate clinical summary    │   │
  └─────────┘           │  └──────────────────────────────┘   │
                        └─────────────────────────────────────┘
```

---

## UC-01 — Submit voice check-in

**Actor:** Patient  
**Preconditions:** Browser with microphone access; patient ID known  
**Trigger:** Patient initiates a scheduled check-in

### Primary flow

1. Patient opens the dashboard URL in a browser.
2. Patient enters their Patient ID in the text field.
3. Patient clicks **Start Recording**.
4. Browser requests microphone permission; patient grants it.
5. Patient speaks their check-in (symptoms, medications, meals, concerns).
6. Patient clicks **Stop Recording**.
7. Recorded audio appears as a playback widget; patient reviews it.
8. Patient clicks **Submit**.
9. System saves the audio file and creates a job with status `processing`.
10. System returns `job_id` to the browser.
11. System confirms submission with status message.

### Alternative flows

| Step | Condition | Outcome |
|---|---|---|
| 4 | Patient denies microphone permission | Alert shown: "Microphone access denied". Recording does not start. |
| 8 | Patient ID field is empty | Alert shown: "Please enter a patient ID". Submission blocked. |
| 8 | No audio has been recorded | Alert shown: "Please record audio first". Submission blocked. |
| 8 | Audio file exceeds 50 MB | Server returns `413 Request Entity Too Large`. Status box shows error. |
| 9 | Network error during upload | Status box shows error message. Patient may retry. |

**Postconditions:** Job exists in `job_store` with status `processing`.

---

## UC-02 — Monitor submission status

**Actor:** Patient  
**Preconditions:** UC-01 completed; `job_id` held by browser  
**Trigger:** Automatic, begins immediately after UC-01

### Primary flow

1. Browser polls `GET /intake/{job_id}` every 2 seconds.
2. Status box updates with current pipeline node (e.g. `last: extract_signals`).
3. On `status=complete` → status box shows "Complete ✓"; dashboard refreshes.
4. On `status=awaiting_review` → status box shows "Paused — awaiting clinician review". Dashboard refreshes to show the orange card.
5. Polling stops.

### Alternative flows

| Condition | Outcome |
|---|---|
| `status=error` | Status box shows error text. Polling stops. |
| Browser tab closed before completion | No further polling. Job continues processing server-side. |

---

## UC-03 — View intake dashboard

**Actor:** Clinician  
**Preconditions:** At least one intake in `complete` or `awaiting_review` state  
**Trigger:** Clinician opens the dashboard; auto-refreshes every 10 seconds

### Primary flow

1. Clinician opens http://localhost:5173.
2. System calls `GET /dashboard` and returns all visible intakes sorted by risk (CRITICAL first) then recency.
3. Dashboard renders intake cards with risk colour coding.
4. Header shows live CRITICAL count badge and awaiting-review count.
5. Every 10 seconds the dashboard silently refreshes.

### Card information displayed

- Risk level badge (colour-coded)
- Patient ID
- Timestamp
- Summary preview (first 200 characters)
- "Awaiting Clinician Review" banner (if paused)

---

## UC-04 — Review flagged intake

**Actor:** Clinician  
**Preconditions:** At least one intake with `requires_human_review=True` or `status=awaiting_review`  
**Trigger:** Clinician clicks an intake card

### Primary flow

1. Clinician clicks a card.
2. Detail modal opens showing:
   - Risk level badge and status
   - Patient ID and timestamp
   - **Approve panel** (if `awaiting_review`) or **Review Required banner**
   - Full clinical summary (if complete)
   - Clinical signals as formatted JSON
   - Meal/nutritional data as formatted JSON
   - Node latency breakdown
   - Risk reasons list
   - Human review note (if set)
3. Clinician reads all sections.
4. Clinician closes modal by clicking ✕ or backdrop.

---

## UC-05 — Approve paused pipeline

**Actor:** Clinician  
**Preconditions:** Intake has `status=awaiting_review`  
**Trigger:** Clinician decides the intake is safe to proceed after UC-04

### Primary flow

1. Clinician reads clinical signals and risk reasons in the modal.
2. Clinician optionally enters a note in the **Clinician Note** textarea (e.g. *"Contacted patient — directed to ED"*).
3. Clinician clicks **Approve & Generate Summary**.
4. Browser sends `POST /intake/{job_id}/approve` with the note.
5. System calls `graph.update_state()` to inject the note, then `graph.invoke(None)` to resume.
6. Only `generate_summary` runs — all earlier nodes are skipped (state is checkpointed).
7. Modal updates to "Generating Summary…" while polling.
8. On completion, full clinical summary appears in the modal.
9. Dashboard card updates to green/orange/red depending on final risk level.

### Alternative flows

| Condition | Outcome |
|---|---|
| Approve clicked on a job that is not `awaiting_review` | Server returns `409 Conflict`. Error shown in modal. |
| Summary generation fails | Job status set to `error`. Error note shown in modal. |
| Clinician closes modal during generation | Modal closes; dashboard auto-refresh will show completion when ready. |

**Postconditions:** Job status is `complete`; `clinical_summary` is populated; `human_review_note` contains clinician comment.

---

## UC-06 — View clinical summary

**Actor:** Clinician  
**Preconditions:** Intake has `status=complete`  
**Trigger:** Clinician clicks any completed intake card

### Summary sections displayed

| Section | Content |
|---|---|
| Patient Check-In Summary | Date, patient ID, risk level, overall narrative |
| Key Findings | Medications, adherence, symptoms, vital concerns |
| Nutritional Assessment | Meal quality, glycemic concerns, caloric estimate |
| Action Items | Recommended follow-up, referrals, dose adjustments |
| Patient Concerns | Verbatim or summarised concerns raised by patient |

---

## UC-07 — Transcribe audio (System)

**Actor:** System  
**Preconditions:** Audio file saved to `/tmp/onsera_audio/`  
**Trigger:** First node of LangGraph pipeline invocation

### Flow

1. System opens audio file for reading.
2. System sends file to Groq `whisper-large-v3` endpoint.
3. Groq returns transcript as plain text.
4. System stores transcript in `AgentState.transcript`.
5. System records transcription latency in `latency_ms["transcribe"]`.

### Error handling

- Groq API timeout or error: exception propagates to `_run_pipeline`, job set to `error`.
- File not found: `OSError` raised; job set to `error`.

---

## UC-08 — Extract clinical signals (System)

**Actor:** System  
**Preconditions:** `transcript` populated in state  
**Trigger:** `extract_signals` node

### Flow

1. System calls Claude Sonnet with `ClinicalSignals` Pydantic schema via `with_structured_output()`.
2. Anthropic returns a tool-call response matching the schema.
3. LangChain validates response against `ClinicalSignals` Pydantic model.
4. System stores serialised signals in `AgentState.clinical_signals`.

### Error handling

- Schema validation failure: `extraction_failed=True` set in state. `risk_flag` escalates to HIGH.
- API timeout: same as above.
- **In no case is a parse failure silently absorbed as LOW risk.**

---

## UC-09 — Analyse nutritional content (System)

**Actor:** System  
**Preconditions:** `clinical_signals.meals_mentioned` populated  
**Trigger:** `meal_analysis` node

### Flow

1. If `meals_mentioned` is empty → return default safe values immediately (no API call).
2. Otherwise, call Claude Sonnet with `MealAnalysis` Pydantic schema.
3. Store result in `AgentState.meal_data`.

---

## UC-10 — Risk-stratify patient (System)

**Actor:** System  
**Preconditions:** `transcript`, `clinical_signals`, `meal_data` populated  
**Trigger:** `risk_flag` node

### Flow (deterministic — no LLM)

1. Scan lowercased transcript for critical keyword phrases.
2. If any match → `risk_level=CRITICAL`, `requires_human_review=True`.
3. Else if `extraction_failed=True` → `risk_level=HIGH`, `requires_human_review=True`.
4. Else if `missed_doses=True` AND symptoms present → `risk_level=HIGH`, `requires_human_review=True`.
5. Else if `glycemic_concern=True` AND `exercise_reported=False` → `risk_level=MEDIUM`.
6. Else → `risk_level=LOW`.

### Safety invariants

- The same transcript must always produce the same risk level (no randomness).
- No external calls are made.
- Execution time is O(n) in transcript length — bounded to milliseconds.

---

## UC-11 — Generate clinical summary (System)

**Actor:** System  
**Preconditions:** All upstream nodes complete; if HIGH/CRITICAL, clinician has approved (UC-05)  
**Trigger:** `generate_summary` node

### Flow

1. Assemble prompt from all state fields (transcript, signals, meal data, risk level, review note).
2. Call Claude Sonnet with structured markdown instructions.
3. Store response in `AgentState.clinical_summary`.
4. Graph execution ends.

---

## Use case priority matrix

| Use Case | Frequency | Criticality | Notes |
|---|---|---|---|
| UC-01 Submit check-in | High (daily per patient) | High | Core patient-facing action |
| UC-02 Monitor status | High | Medium | UX quality; failure is cosmetic |
| UC-03 View dashboard | High | High | Primary clinician workflow |
| UC-04 Review flagged | Medium | Critical | Safety-critical action |
| UC-05 Approve pipeline | Medium | Critical | Directly governs summary generation |
| UC-06 View summary | High | High | Core clinical value |
| UC-07 Transcribe | High | High | Pipeline entry point |
| UC-08 Extract signals | High | Critical | Extraction failure escalates to HIGH |
| UC-09 Meal analysis | High | Medium | Skipped safely if no meals |
| UC-10 Risk-stratify | High | Critical | Deterministic safety gate |
| UC-11 Generate summary | High | High | Final clinical output |
