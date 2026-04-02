# ADR-002 — LangGraph for Pipeline Orchestration

**Date:** 2026-04-02  
**Status:** Accepted  
**Deciders:** Engineering

---

## Context

The intake pipeline has six distinct processing steps with conditional routing,
shared state, and a human-in-the-loop pause requirement. We needed a
framework to orchestrate these steps reliably.

Options considered: plain Python functions, LangChain LCEL chains, LangGraph,
Prefect/Airflow.

---

## Decision

Use **LangGraph `StateGraph`** for pipeline orchestration, compiled with a
**`MemorySaver` checkpointer**.

---

## Consequences

### Positive

- **Built-in state management.** `AgentState` (TypedDict) flows through all
  nodes. Each node returns only the fields it modifies — LangGraph merges
  updates. This is cleaner than passing a mutable dict manually.

- **Conditional routing as a first-class primitive.** `add_conditional_edges`
  makes the `risk_flag → human_review_gate OR generate_summary` branch
  explicit and testable. The routing logic is not buried in application code.

- **`NodeInterrupt` + checkpointing.** LangGraph's interrupt/resume model
  is exactly what human-in-the-loop requires: the graph genuinely pauses,
  persists state to the checkpointer, and resumes from the exact node where
  it stopped. No earlier nodes re-execute. This is cheaper and more correct
  than re-running the pipeline.

- **Observability.** Each node is a named unit. Latency can be tracked per
  node. Future versions could use LangGraph's built-in tracing.

- **Graph visualisation.** LangGraph can export the compiled graph as a
  Mermaid diagram for documentation.

### Negative

- **Learning curve.** LangGraph's state merge semantics (especially the
  `add_messages` reducer) are non-obvious to engineers unfamiliar with the
  framework.

- **Synchronous `.invoke()`.** LangGraph 0.2 `invoke()` is synchronous,
  requiring `ThreadPoolExecutor` in the FastAPI layer. An async-native graph
  would be simpler.

- **Version sensitivity.** LangGraph 0.2.38 is pinned tightly. Minor version
  upgrades have broken the `NodeInterrupt` API in the past.

- **Overkill for a linear pipeline.** For the happy path (LOW/MEDIUM cases),
  the graph is essentially a sequential chain. LangGraph's value becomes
  clear only when human-in-the-loop is exercised.

---

## Alternatives considered

### Option A: Plain Python functions

Call each processing function sequentially. Use `if/else` for routing.

**Rejected because:**
- No built-in state management or checkpointing.
- Implementing human-in-the-loop pause/resume would require custom
  infrastructure (database, job queue, resumption logic).
- Harder to add parallelism or retry logic later.

### Option B: LangChain LCEL

Use LCEL `RunnableSequence` with `RunnableBranch` for routing.

**Rejected because:**
- LCEL does not natively support `NodeInterrupt` / graph interruption.
- State management is less structured than LangGraph's TypedDict.
- Checkpointing requires additional work.

### Option C: Prefect / Airflow

Use a workflow orchestration system designed for data pipelines.

**Rejected because:**
- Designed for long-running batch workflows, not real-time API-driven
  conversational pipelines.
- Significant infrastructure overhead (separate workers, scheduler, UI).
- Does not integrate naturally with LangChain/Anthropic tooling.

---

## Future considerations

- Upgrade to LangGraph's async `.ainvoke()` when available and stable, to
  remove the `ThreadPoolExecutor` requirement in FastAPI.
- Replace `MemorySaver` with `AsyncSqliteSaver` or a PostgreSQL-backed
  checkpointer for persistence across server restarts.
- Enable LangGraph's built-in streaming to reduce time-to-first-token on
  `generate_summary`.
