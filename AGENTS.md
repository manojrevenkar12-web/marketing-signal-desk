# Working on Signal Desk

## Fast feedback

```bash
pg_ctlcluster 16 main start            # or: docker compose up db
.venv/bin/pytest -q                    # 76 tests, ~70 s (needs DATABASE_URL to an ordinary, non-superuser role)
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy src
.venv/bin/python manage.py evals dev   # end to end over scenarios/dev, writes reports/evals/dev.json
.venv/bin/python manage.py evals robustness
cd frontend && npm run build           # Tailwind v4 + vendored htmx/Alpine; CI fails if the built CSS differs
```

CI (`.github/workflows/ci.yml`) runs all of the above, `makemigrations --check`, `evals all` and fails
if a committed report changes, then builds the image and validates the Terraform.

## Invariants (each has a test; keep it that way)

1. **Tenancy is enforced by PostgreSQL.** Every workspace table has row-level security with
   `FORCE`; requests run inside `workspace_scope()`. Tests connect as a non-superuser so RLS
   applies to them (`tests/test_rls.py`). A new workspace table needs `enable_rls` in a migration.
2. **Rules decide, models write.** Causes come from the Shapley decomposition and the data checks in
   `msd.analysis`; budget proposals come from `msd.proposals.engine` over `config/proposals.yaml`.
   The language model only reads the question into a `QuestionPlan` and words the facts.
3. **Every number shown is traced.** `msd.assistant.grounding.verify` checks each number in an answer
   against the facts at its stated precision. One correction round, then the deterministic template.
   Untraced numbers shipped is an eval metric and must stay 0.
4. **Platform text is data.** Campaign names reach a model only inside the facts, cleaned by
   `facts.clean_name`.
5. **People approve money.** Only a manager can approve or reject a proposal, once; every decision is
   in the append-only, hash-chained audit trail (`AuditEvent`, trigger `msd_audit_append_only`).
6. **Decision code never sees the truth.** Only `msd.sim` and `msd.evals` read a scenario's truth
   (`tests/test_isolation.py`). Connectors talk to the simulator only for accounts in `sim` mode.
7. **Settings live in `config/`**, not in code: windows, materiality, signal thresholds, guardrails,
   providers and models.
8. **Content Security Policy without `unsafe-inline` or `unsafe-eval`.** Use the Alpine CSP build,
   `Alpine.data` components and `data-*` hooks; never inline handlers.

## The held-out rule

`heldout/blind-1` was written blind from `heldout/WRITING_SCENARIOS.md` by someone who had not seen
the code. Its first run is `reports/heldout/blind-1/first_run.json` and is never rewritten; the set
and the run are pinned in `tests/test_heldout.py`.

- Never change analysis, thresholds or prompts to pass a held-out scenario.
- If you study its failures, write `regression` to `heldout/blind-1/STATUS`, move the files to
  `scenarios/dev/`, and have someone who has not seen the code write a new set from the guide only.

## Where things are

| Path | What |
|---|---|
| `src/msd/connectors` | Google Ads, Meta, Microsoft Ads, TikTok, GA4 clients; retries; window sync |
| `src/msd/sim` | Simulated advertiser and fake platform APIs (with faults) |
| `src/msd/analysis` | Dataset, data checks, Shapley decomposition, causes |
| `src/msd/proposals` | Guarded budget proposals, decisions, audit chain |
| `src/msd/assistant` | Question plans, facts, LangChain writers, grounding |
| `src/msd/web` | Views, template partials for HTMX, presenters |
| `src/msd/evals` | Scenario runner, grading, robustness |
| `infra/gcp` | Cloud Run service + worker pool + nightly sync job, Cloud SQL, Secret Manager |
