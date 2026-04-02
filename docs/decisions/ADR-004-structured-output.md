# ADR-004 — Structured Output via Pydantic + with_structured_output()

**Date:** 2026-04-02  
**Status:** Accepted  
**Deciders:** Engineering

---

## Context

The `extract_signals` and `meal_analysis` nodes need Claude to return
structured data that the downstream `risk_flag` node and `generate_summary`
node can consume programmatically.

Two approaches were available:
1. Prompt the model to return JSON, then parse the string response.
2. Use LangChain's `with_structured_output()` with a Pydantic schema, which
   uses Anthropic's tool-calling API to enforce structured output.

The initial implementation used approach 1. During the hardening phase,
approach 2 was adopted.

---

## Decision

Use **`with_structured_output(PydanticModel)`** for both `extract_signals`
and `meal_analysis`, backed by Pydantic v2 schemas (`ClinicalSignals` and
`MealAnalysis`).

---

## Rationale

### The problem with JSON prompting

The previous approach prompted Claude with:

> "Return ONLY valid JSON with exactly these fields (no extra text, no
> markdown fences): ..."

This required a defensive `_parse_json_response()` helper that stripped
markdown code fences before calling `json.loads()`. It had several failure
modes:

1. Claude occasionally wraps output in ` ```json ` fences despite instruction.
2. Claude may return a string `"true"` instead of boolean `true`.
3. Claude may omit optional fields entirely.
4. A schema change requires updating both the prompt and the parser.
5. There is no validation that `missed_doses` is actually a boolean — it
   could be a string, an integer, or a nested object.

Each of these failure modes could produce incorrect risk classification.

### The structured output solution

`with_structured_output(ClinicalSignals)` uses Anthropic's tool-calling API.
The schema is sent as an Anthropic tool definition. The model is forced to
invoke the tool with arguments that match the schema. LangChain then
validates the response against the Pydantic model before returning it.

Benefits:
- **Schema validation is guaranteed.** `missed_doses` is always a Python
  `bool`. `meal_quality_score` is always an `int` between 1 and 10 (Pydantic
  `Field(ge=1, le=10)`).
- **Field descriptions are surfaced to the model.** Pydantic `Field(...,
  description="...")` annotations are included in the tool schema, giving the
  model richer context than a prompt alone.
- **No string parsing.** `_parse_json_response()` is eliminated.
- **Schema changes are automatic.** Updating the Pydantic model updates the
  tool schema sent to the API. No prompt editing required.

### Failure escalation

When `with_structured_output()` fails (API error, unexpected model response),
LangChain raises an exception. The `extract_signals` node catches this,
sets `extraction_failed=True`, and returns. The `risk_flag` node checks this
field and immediately escalates to HIGH risk.

This is strictly safer than the previous approach, which caught parse errors
and returned a zeroed-out default dict — causing the pipeline to continue
with incorrect signals and potentially produce a LOW risk classification for
a genuinely dangerous case.

---

## Consequences

### Positive

- Schema-enforced extraction — boolean fields are booleans, integer fields
  are integers.
- Field-level documentation in the Pydantic models serves as living
  specification.
- Failure escalates rather than suppresses.
- Less application code (no JSON parsing helper).

### Negative

- Tool-calling adds one round-trip overhead in the Anthropic API (marginally
  more latency than a text completion).
- `with_structured_output()` behaviour is tied to LangChain's implementation,
  which may change across versions.
- Very large or complex schemas may exceed the model's context for tool
  definitions (not a concern for our schemas at current size).

---

## Alternatives considered

### Option A: JSON mode (response_format)

Some models support a `response_format={"type": "json_object"}` parameter
that guarantees valid JSON output.

**Rejected because:**
- Does not guarantee schema conformance — only that the output is valid JSON.
- Does not prevent `missed_doses` from being returned as a string.
- Not available in all Anthropic model versions at the time of writing.

### Option B: JSON prompting with strict validation

Keep JSON prompting but add explicit Pydantic validation after parsing.

**Rejected because:**
- Still requires string parsing with all its failure modes.
- Adds code without removing the root cause (unstructured text output).
- Two-step approach is strictly inferior to using the API's native structured
  output capability.

---

## Future considerations

- Add `model_validator` decorators to `ClinicalSignals` for cross-field
  validation (e.g. if `missed_doses=True`, `medications` list must be
  non-empty).
- Expose Pydantic schema as a JSON Schema endpoint (`GET /schema/clinical-signals`)
  for downstream consumers.
