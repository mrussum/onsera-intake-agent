# ADR-001 — Deterministic Python for Risk Flagging

**Date:** 2026-04-02  
**Status:** Accepted  
**Deciders:** Engineering, Clinical Safety

---

## Context

The intake pipeline must classify each patient check-in into one of four risk
levels: LOW, MEDIUM, HIGH, CRITICAL. CRITICAL and HIGH cases require immediate
human review and must never be silently missed.

The question was whether to use an LLM for risk classification (since it is
already used for signal extraction and summary generation) or to implement
risk stratification in deterministic code.

---

## Decision

The `risk_flag` node is implemented as **pure Python with no LLM involvement**.
Risk classification is based on:

1. Keyword matching against the raw transcript (for CRITICAL)
2. Boolean logic over extracted clinical signals (for HIGH and MEDIUM)
3. Default to LOW

The rules are explicitly enumerated, version-controlled, and covered by unit
tests that run in milliseconds.

---

## Consequences

### Positive

- **Auditability.** Every risk classification decision can be traced to a
  specific rule in `intake_graph.py`. There is no black box.

- **Determinism.** The same transcript always produces the same risk level.
  This is a regulatory requirement for clinical decision support software
  and essential for regression testing.

- **Speed.** The risk flag node runs in < 1 ms. No API call, no token cost,
  no latency.

- **Safety under adversarial conditions.** An LLM can be prompt-injected via
  patient-controlled transcript content. A patient could potentially craft a
  transcript that causes an LLM to classify a critical case as low risk.
  Keyword matching on the raw text is not susceptible to this attack.

- **No hallucination risk.** LLMs occasionally produce inconsistent outputs.
  A hallucinated "LOW" classification for a patient saying "chest pain" would
  be a patient safety incident.

- **Testable as a safety gate.** Unit tests can assert with 100% confidence
  that a given transcript produces a given risk level. This is the foundation
  of the CI safety gate.

### Negative

- **Limited coverage.** Keyword matching misses synonyms and context. A patient
  saying "I feel like my heart is being squeezed" would not trigger CRITICAL
  even though it describes a potential cardiac event.

- **Maintenance overhead.** The keyword list must be maintained as clinical
  knowledge evolves. A governance process is required to update it safely.

- **Context-blindness.** "arm pain" triggers CRITICAL even if the patient is
  describing post-vaccination soreness. This produces false positives, which
  generate unnecessary human review load.

---

## Alternatives considered

### Option A: LLM-based classification

Prompt Claude to classify risk level based on the transcript.

**Rejected because:**
- Non-deterministic. The same transcript may produce different outputs on
  different runs.
- Susceptible to prompt injection via transcript content.
- Unauditable. Cannot explain to a regulator exactly why a case was classified
  LOW.
- Adds latency and token cost to the critical path.

### Option B: Hybrid (LLM + deterministic override)

Use LLM for broad classification but add a deterministic override layer for
critical keywords.

**Rejected because:**
- Increases complexity without clear benefit. The deterministic layer would
  need to be authoritative for safety cases anyway, making the LLM layer
  redundant on the critical path.
- Harder to test and audit.

---

## Future considerations

- Add co-occurrence rules (e.g. "arm pain" only triggers CRITICAL when
  accompanied by "chest pain") to reduce false positives.
- Integrate a clinical terminology system (SNOMED CT) for synonym expansion.
- Consider a secondary LLM-assisted triage that runs in parallel but never
  overrides the deterministic gate — only adds context.
