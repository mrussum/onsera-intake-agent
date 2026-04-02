# ADR-003 — Human-in-the-Loop via NodeInterrupt

**Date:** 2026-04-02  
**Status:** Accepted  
**Deciders:** Engineering, Clinical Safety

---

## Context

HIGH and CRITICAL intakes must not have clinical summaries generated without
a clinician first reviewing the extracted signals. This is a regulatory and
clinical safety requirement.

The question was how to implement the pause: should the system generate the
summary immediately and flag it for review, or should it genuinely withhold
summary generation until a clinician explicitly approves?

---

## Decision

Use LangGraph's **`NodeInterrupt`** mechanism with **`MemorySaver`
checkpointing** to genuinely pause graph execution before `generate_summary`.

The `human_review_gate` node raises `NodeInterrupt(payload)`, which:
1. Immediately halts pipeline execution
2. Persists the full `AgentState` snapshot to the checkpointer (keyed by `job_id`)
3. Propagates as `GraphInterrupt` to the calling code in `main.py`
4. Sets job status to `awaiting_review`

When a clinician calls `POST /intake/{job_id}/approve`:
1. Server calls `graph.update_state(config, {"human_review_note": note})`
2. Server calls `graph.invoke(None, config={"configurable": {"thread_id": job_id}})`
3. LangGraph restores the checkpointed state and continues from `human_review_gate`
4. Only `generate_summary` executes — transcription, extraction, and risk flagging do not re-run

---

## Consequences

### Positive

- **Summary is never generated without approval.** The `clinical_summary`
  field is empty in `awaiting_review` jobs. There is no risk of a clinician
  seeing an AI-generated summary before they have approved the case — the
  summary simply does not exist yet.

- **Cheaper resumption.** Only one LLM call (generate_summary) runs after
  approval. The three earlier LLM/API calls (transcription, extraction, meal
  analysis) are not repeated.

- **Clinician note is injected before summary generation.** The approval note
  becomes part of the summary context via `graph.update_state()`. The
  generated summary can reference the clinician's decision (e.g. "Clinician
  directed patient to ED").

- **Audit trail.** The paused state, resumption time, and clinician note are
  all recorded in the job record.

- **True human-in-the-loop semantics.** This is architecturally honest —
  the system does not pretend to pause while silently continuing. The graph
  genuinely stops.

### Negative

- **In-memory persistence only.** `MemorySaver` does not survive a server
  restart. An `awaiting_review` job whose graph state is lost cannot be
  resumed — it must be resubmitted.

- **Single-process limitation.** `MemorySaver` is not shared across multiple
  server instances. Horizontal scaling requires a persistent checkpointer.

- **Approval is all-or-nothing.** The current implementation does not support
  partial approval (e.g. "approve but flag for secondary review"). A more
  sophisticated workflow might allow clinicians to reject a case or request
  re-analysis.

---

## Alternatives considered

### Option A: Generate summary immediately, flag for review

Generate the clinical summary for all intakes. Mark HIGH/CRITICAL cases with
`requires_human_review=True`. The clinician reviews the summary and the
underlying data.

**Rejected because:**
- A summary generated from unreviewed critical signals could be acted upon
  before a clinician has reviewed it. This is a patient safety risk.
- The regulatory position on AI-generated clinical summaries for emergency
  cases without human gate is unclear and potentially non-compliant.

### Option B: Status flag + re-run on approval

Set `status=awaiting_review` without pausing the graph. On approval, re-run
the full pipeline (transcription through summary).

**Rejected because:**
- Re-transcribing and re-extracting wastes API calls and adds latency.
- The audio file has already been deleted after initial processing.
- Does not demonstrate LangGraph's interrupt/resume capability.

### Option C: Separate review queue service

Build a separate microservice that holds flagged intakes. The intake pipeline
writes to a queue; the review service reads from it; on approval, it calls
back to trigger summary generation.

**Rejected because:**
- Significant infrastructure complexity for v1.
- LangGraph already provides the primitives needed (NodeInterrupt +
  checkpointer). Building a separate service duplicates this.

---

## Future considerations

- Replace `MemorySaver` with `AsyncSqliteSaver` or `PostgresCheckpointer`
  for persistence across restarts and horizontal scaling.
- Add a rejection flow: if the clinician rejects the intake (e.g. believes
  the transcript is corrupt), the job is marked `rejected` and the patient
  is notified.
- Add a timeout: if an `awaiting_review` job is not approved within N hours,
  escalate to a senior clinician or page on-call.
- Integrate with a proper task management system (e.g. PagerDuty, Jira) for
  CRITICAL cases.
