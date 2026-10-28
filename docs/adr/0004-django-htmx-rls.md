# 0004: Django 6 with HTMX, Alpine and Tailwind; tenancy in PostgreSQL

## Context

An agency team works across many client workspaces, from one server-rendered app, with a small team
maintaining it.

## Decision

- Django 6.1 template partials serve HTMX fragments from the same template as the page, so there is
  one source of markup. Alpine (CSP build) covers local UI state; Tailwind v4 `@theme` tokens hold
  colour, radius, shadow and motion.
- Django 6's built-in CSP with nonces; no inline handlers.
- Long work (answering, syncing) runs as `django.tasks` tasks: immediate in development,
  `django-tasks-db` workers in production (a Cloud Run worker pool).
- Every workspace table has PostgreSQL row-level security with `FORCE`. The request sets
  `msd.workspace_id` for its transaction, so a query that forgets its filter still sees only one
  workspace.

## Consequences

- Tests and the app must connect as an ordinary role; a superuser bypasses RLS. CI creates one.
- No SPA build and no API layer to keep in step with the UI.
