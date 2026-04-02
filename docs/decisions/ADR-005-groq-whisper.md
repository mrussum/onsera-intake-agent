# ADR-005 — Groq for Speech-to-Text Transcription

**Date:** 2026-04-02  
**Status:** Accepted  
**Deciders:** Engineering

---

## Context

Patient voice recordings must be converted to text before any clinical
processing can occur. Several transcription services are available, including
OpenAI Whisper API, Groq's Whisper hosting, AWS Transcribe, Google
Speech-to-Text, and Azure Cognitive Services.

---

## Decision

Use **Groq's hosted `whisper-large-v3`** for speech-to-text transcription,
accessed via the `groq` Python SDK.

---

## Rationale

### Groq hardware advantage

Groq runs inference on its own LPU (Language Processing Unit) hardware,
which provides significantly lower latency than GPU-based inference for
Whisper. A 60-second audio recording typically transcribes in 1–3 seconds
on Groq, compared to 5–10 seconds on OpenAI's Whisper API.

For a real-time patient intake pipeline where the clinician and patient are
waiting, this latency difference is perceptible and clinically relevant.

### Model quality

`whisper-large-v3` is OpenAI's highest-quality Whisper model. Groq hosts
the same weights as OpenAI — the transcription quality is identical.
The choice of Groq over OpenAI's own Whisper API is purely a latency and
cost optimisation, not a quality trade-off.

### Cost

Groq's Whisper pricing is competitive with OpenAI and in some tiers is lower.
For a healthcare application with high intake volume, this matters.

### Single SDK for audio

Using Groq for Whisper and Anthropic for LLM keeps the SDK count at two.
Using OpenAI for Whisper would introduce a third SDK (openai) even though
OpenAI is not used for any LLM tasks in this system. Minimising dependencies
reduces maintenance burden and potential version conflicts.

---

## Consequences

### Positive

- Low transcription latency (1–3 s for 60 s audio).
- `whisper-large-v3` model quality — strong medical vocabulary recognition.
- No additional OpenAI dependency.
- Simple SDK: `groq.Groq(api_key=...).audio.transcriptions.create(...)`.
- Module-level client singleton avoids reconnection overhead per call.

### Negative

- Groq API key required in addition to Anthropic API key.
- Groq is a newer provider with a shorter reliability track record than
  OpenAI or AWS.
- If Groq experiences an outage, the entire intake pipeline is blocked
  (transcription is the first node).
- No on-premises deployment option — audio is sent to Groq's cloud.
  For strict data residency requirements, this would be a blocker.

---

## Alternatives considered

### Option A: OpenAI Whisper API

Use `openai.audio.transcriptions.create()` with `whisper-1` or `whisper-large-v3`.

**Not chosen because:**
- Higher latency than Groq for equivalent models.
- Introduces the `openai` SDK as a dependency when OpenAI is not used
  anywhere else in the system.
- The interview specification explicitly requires Groq.

### Option B: AWS Transcribe

AWS managed speech-to-text service.

**Not chosen because:**
- Requires AWS credentials and SDK, which is significant added complexity.
- Higher latency for short audio (job-based API, not real-time for short
  recordings).
- More expensive at low volume.

### Option C: Local Whisper (self-hosted)

Run `whisper-large-v3` locally using `faster-whisper` or `transformers`.

**Not chosen because:**
- Requires GPU or high-memory CPU instance.
- Significantly increases Docker image size and deployment complexity.
- Not practical for a cloud-hosted API service.
- Appropriate for on-premises deployments with strict data residency
  requirements — worth considering in a production context.

---

## Future considerations

- Add a fallback transcription provider (e.g. OpenAI Whisper) that activates
  when Groq is unavailable. The `transcribe` node is a clean boundary for
  this abstraction.
- For data residency requirements, evaluate `faster-whisper` on dedicated
  GPU infrastructure.
- Add medical vocabulary prompting to the Whisper call — Groq's API supports
  a `prompt` parameter that can prime the model with domain-specific terms
  (medication names, clinical vocabulary), improving accuracy.
