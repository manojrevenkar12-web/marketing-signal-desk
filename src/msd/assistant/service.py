"""Answer a question: plan it, run the diagnosis, propose, write it up, check every number.

The steps run in a background task (django.tasks); the page polls the question until it is
answered. Each step's result is stored on the Question, so a failure says where it failed.
"""

from __future__ import annotations

import logging
from typing import Any

from django.tasks import task

from msd.analysis import service as analysis
from msd.assistant import facts as facts_mod
from msd.assistant.grounding import verify
from msd.assistant.models import Question
from msd.assistant.plan import PlanProblem, check
from msd.assistant.writers import Writer, default_writer, template
from msd.conf import read
from msd.proposals import engine
from msd.tenancy.models import Workspace
from msd.tenancy.scope import workspace_scope

log = logging.getLogger("msd.assistant")
_writer: Writer | None = None


def writer() -> Writer:
    global _writer
    if _writer is None:
        _writer = default_writer()
    return _writer


def set_writer(w: Writer | None) -> None:
    """Tests and evals choose the writer."""
    global _writer
    _writer = w


def ask(workspace_id: int, user: Any, text: str) -> Question:
    with workspace_scope(workspace_id):
        q = Question.objects.create(workspace_id=workspace_id, asked_by=user, text=text.strip()[:500])
    answer_question.enqueue(q.pk, workspace_id)
    return q


@task()
def answer_question(question_id: int, workspace_id: int) -> str:
    with workspace_scope(workspace_id):
        q = Question.objects.get(pk=question_id)
        q.status = Question.Status.RUNNING
        q.save(update_fields=["status"])
    try:
        _answer(q)
    except Exception as e:  # the question records the failure; the page shows it with a retry
        log.exception("question %s failed", question_id)
        q.status, q.error = Question.Status.FAILED, f"{type(e).__name__}: {e}"[:2000]
    with workspace_scope(workspace_id):
        q.save()
    return q.status


def _answer(q: Question) -> None:
    w = writer()
    q.model = w.name
    try:
        ds = analysis.load(q.workspace_id)
    except analysis.NoData as e:
        q.status, q.answer = Question.Status.ANSWERED, str(e).capitalize() + "."
        return
    plan = w.plan(q.text, ds.first_day, ds.last_day)
    try:
        plan = check(plan, ds.first_day, ds.last_day)
    except PlanProblem as e:
        q.plan, q.status, q.answer = plan.model_dump(mode="json"), Question.Status.ANSWERED, f"I cannot answer that for these dates: {e}."
        return
    q.plan = plan.model_dump(mode="json")
    if not plan.supported:
        q.status, q.answer = Question.Status.ANSWERED, plan.reason or "I can explain why CPA or ROAS changed for this workspace."
        return
    base = (plan.baseline_start, plan.baseline_end) if plan.baseline_start else None
    diag = analysis.run(q.workspace_id, plan.metric, plan.source, (plan.current_start, plan.current_end), base)  # type: ignore[arg-type]
    q.diagnosis = diag
    made = engine.create(diag) if diag.material else []
    with workspace_scope(q.workspace_id):
        currency = Workspace.objects.get(pk=q.workspace_id).currency
    props = [{"title": p.title, "action": p.action, "budget_change_per_day": float(p.budget_change_per_day) if p.budget_change_per_day is not None else None} for p in made]
    facts = facts_mod.build(diag.result, props, currency)
    allowed = facts_mod.numbers(facts)
    text = w.write(facts)
    rep = verify(text, allowed, exempt=[q.text])
    retries = read("llm")["grounding_retries"]
    while not rep.ok and retries > 0:
        retries -= 1
        q.corrections += 1
        listed = "; ".join(s.text for s in rep.untraced)
        text = w.write(facts, feedback=f"These numbers are not in the FACTS: {listed}. Rewrite the answer without them, using only numbers from the FACTS.")
        rep = verify(text, allowed, exempt=[q.text])
    if not rep.ok:
        text = template(facts)
        rep = verify(text, allowed, exempt=[q.text])
        q.fallback = True
    q.answer, q.numbers, q.status = text, rep.as_list(), Question.Status.ANSWERED
