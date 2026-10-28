# Signal Desk

**Why did our CPA go up last week?** Signal Desk answers that for a performance-marketing team,
across Google Ads, Meta, Microsoft Ads, TikTok and GA4. It checks the data first, decides the causes
with an exact decomposition, has a language model explain them with every number traced, and puts
budget changes in front of a manager for approval.

Django 6.1 · HTMX · Alpine.js · Tailwind CSS v4 · PostgreSQL 16 (row-level security) ·
LangChain over Anthropic, OpenAI and OpenRouter · LangSmith · django.tasks · Docker · GitHub
Actions · Terraform for Google Cloud Run.

![Overview: the CPA bridge and what moved it](docs/screenshots/overview.png)

## What it does

1. **Connects** to the five platforms through their real API shapes: Google Ads `googleAds:search`
   (micros as strings, page tokens), Meta Insights (purchases repeated under several action types,
   cursor paging), Microsoft Ads reports (submit, poll, download a zipped CSV with header lines),
   TikTok `report/integrated/get` (30-day limit), GA4 `runReport` (key events, offset paging).
   Retries absorb 429 and 503; a sync replaces its window so reruns are safe.
2. **Checks the data** before explaining anything: GA4 tracking gaps, platform over-reporting,
   invalid traffic, missing days ([ADR 0002](docs/adr/0002-check-the-data-first.md)).
3. **Decomposes** the move in CPA or ROAS into spend mix and each channel's CPM, CTR, CVR (and order
   value) with exact Shapley values, so the parts add up to the change
   ([ADR 0001](docs/adr/0001-shapley-bridge.md)). Causes must be material and outside normal
   week-to-week noise.
4. **Proposes** budget changes from rules with guardrails (hold on a tracking problem, exclude
   invalid traffic, shift out of auction pressure) and records a manager's decision in an
   append-only, hash-chained audit trail.
5. **Answers questions** in plain language. The model reads the question into a typed plan and words
   the facts; it never decides. Every number it writes is checked against the analysis, and an
   answer that cannot be traced falls back to the template
   ([ADR 0003](docs/adr/0003-models-write-not-decide.md)).

![Ask: a grounded answer with traced numbers and the proposals it led to](docs/screenshots/ask.png)

## Measured

All numbers come from `python manage.py evals all` and are committed in `reports/`; CI fails if
they change. Scenarios are a simulated advertiser (7 campaigns, 4 channels, GA4) with known causes,
fetched through the fake APIs with injected faults and run end to end: sync, data checks,
analysis, task queue and writer.

| Set | Top cause right | Cause recall | Data problems found | Untraced numbers shipped | Wrong budget cuts / day (naive rule) |
|---|---|---|---|---|---|
| Development, 13 scenarios | 13 / 13 | 1.00 | 6 / 6, 0 false | 0 | 0 EUR (3,901 EUR) |
| Robustness, 13 × 10 seeds | 125 / 130 fully right (96.2%) | | | | |
| **Blind held-out, 25 scenarios, first run** | **21 / 25** | **0.88** | **7 / 10, 2 false** | **0** | **0 EUR (3,751 EUR)** |

The blind set was written by someone who saw only [the scenario guide](heldout/WRITING_SCENARIOS.md),
never the code. Its first run (`reports/heldout/blind-1/first_run.json`) is recorded once and pinned
by sha256; the code is not changed to pass it. It missed five scenarios, mostly where a tracking
or over-reporting problem overlaps a real performance change; 6 false causes were reported.

Other numbers: the Shapley parts add to the change within 1e-14; every sync reconciled to the
platform totals; 300 transient API faults were absorbed in the blind run; the grounding check
corrected 8 answers and none needed the template fallback.

## Run it

```bash
docker compose up -d db
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py seed_demo
docker compose up web worker      # http://localhost:8000, user max / signal-desk-demo (manager)
```

Without keys the simulated writer is used. Set `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` or
`OPENROUTER_API_KEY` (any subset; they back each other up) and `LANGSMITH_TRACING=true` with
`LANGSMITH_API_KEY` to trace. Models and providers are in `config/llm.yaml`.

The demo agency has three workspaces: Lumen Skincare (auction pressure plus bot clicks), Northwind
Outdoor (a push into TikTok) and Kaffeehaus Berg (a broken Meta tag). Users: `anna` (analyst),
`max` (manager), `lumen-client` (client, read-only).

### Development

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]" -c constraints.txt
export DATABASE_URL=postgresql://msd:msd@localhost:5432/msd   # an ordinary role, so RLS applies
.venv/bin/pytest -q                                           # 76 tests incl. Playwright end to end
.venv/bin/python manage.py evals all
cd frontend && npm ci && npm run build
```

See [AGENTS.md](AGENTS.md) for the invariants and the held-out rule.

## Deploy

`infra/gcp` holds Terraform for Cloud Run (web service, a worker pool running `db_worker`, a nightly
sync job on Cloud Scheduler), Cloud SQL for PostgreSQL 16 on a private IP, Secret Manager for
platform tokens and model keys, and a VPC. The image is built in CI from the multi-stage
`Dockerfile` (Tailwind assets, then the Python app under gunicorn with uvicorn workers).

## Security

- Tenancy enforced in PostgreSQL with row-level security (`FORCE`), tested as a non-superuser.
- Roles: analyst, manager, client. Only managers decide proposals; clients cannot ask or sync.
- Content Security Policy with nonces and no `unsafe-inline` or `unsafe-eval` (Alpine CSP build).
- Campaign names from the platforms are cleaned of instructions before they reach a model.
- Platform credentials are referenced by name and read from the environment or Secret Manager.

## Limits

- All data is simulated. The connectors follow the documented API shapes but have not been run
  against live advertiser accounts, and the live LLM providers have not been run through the evals.
- The Terraform is validated in CI, not deployed.
- The blind run is 25 scenarios from one writer; it measures this analysis on this simulator, not on
  real accounts.
- Two KPIs (CPA and ROAS); no attribution modelling beyond comparing GA4 with the platforms.
