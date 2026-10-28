# 0003: The language model reads and writes; it does not decide

## Context

An LLM asked "why did CPA rise?" over raw rows will produce a fluent answer with numbers it computed
itself, sometimes wrongly, and campaign names written by anyone with platform access can carry
instructions.

## Decision

- The model turns the question into a typed `QuestionPlan` (metric, source, dates) through LangChain
  structured output, with a `PydanticOutputParser` fallback. Plans are validated against the data's
  dates.
- The analysis decides the causes and the proposals; the model words a JSON of facts.
- Every number in the answer is checked against the facts at the precision it is stated. Untraced
  numbers get one correction round, then the deterministic template is shown instead.
- Providers are Anthropic, OpenAI and OpenRouter through `with_fallbacks`; LangSmith tracing is
  switched on by environment. CI and the evals use a simulated writer that deliberately adds a
  derived number 30% of the time, so the grounding check is exercised on every run.

## Consequences

- The answer can be wrong only where the analysis is wrong, and the evals measure the analysis.
- Live providers have not been run against this repository's evals; the README says so.
