"""Pages and HTMX fragments. Full pages render `page.html`; HTMX requests get the named partial
(Django 6 template partials, `template.html#name`), so one template holds both."""

from __future__ import annotations

from typing import Any

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from msd.analysis import service as analysis
from msd.analysis.models import Diagnosis
from msd.assistant import service as assistant
from msd.assistant.models import Question
from msd.connectors.models import ConnectorAccount, SyncRun
from msd.connectors.sync import default_window, sync
from msd.metrics.models import AdDaily
from msd.proposals import engine
from msd.proposals.models import AuditEvent, Proposal
from msd.tenancy.models import Membership
from msd.web.access import workspace_view
from msd.web.presenters import answer_segments, bridge, cause_cards, channel_label

SUGGESTIONS = [
    "Why did our CPA go up last week?",
    "Why did ROAS drop last week?",
    "Why did CPA change in the platforms' own numbers last week?",
    "What happened to CPA from 14 Sep to 20 Sep?",
]


def _ctx(request: HttpRequest, **kw: Any) -> dict[str, Any]:
    return {"ws": request.workspace, "member": request.membership, "workspaces": Membership.objects.filter(user_id=request.user.pk or 0).select_related("workspace"), **kw}  # type: ignore[attr-defined]


def _htmx(request: HttpRequest) -> bool:
    return request.headers.get("HX-Request") == "true"


@require_GET
def health(request: HttpRequest) -> JsonResponse:
    with connection.cursor() as c:
        c.execute("SELECT 1")
    return JsonResponse({"status": "ok"})


@login_required
def home(request: HttpRequest) -> HttpResponse:
    ms = list(Membership.objects.filter(user_id=request.user.pk or 0).select_related("workspace", "workspace__agency"))
    if len(ms) == 1:
        return redirect("overview", slug=ms[0].workspace.slug)
    return render(request, "web/home.html", {"memberships": ms})


# --- overview -------------------------------------------------------------------------------------


@workspace_view()
def overview(request: HttpRequest) -> HttpResponse:
    ws = request.workspace  # type: ignore[attr-defined]
    has_data = AdDaily.objects.filter(workspace=ws).exists()
    return render(request, "web/overview.html", _ctx(request, has_data=has_data, section="overview"))


@workspace_view()
def overview_diagnosis(request: HttpRequest) -> HttpResponse:
    """The week against the four before it, computed when the page asks for it (lazy HTMX load)."""
    ws = request.workspace  # type: ignore[attr-defined]
    try:
        ds = analysis.load(ws.pk)
        base, cur = analysis.periods_for(ds)
        diag = Diagnosis.objects.filter(workspace=ws, metric="cpa", source="ga4", current_start=cur.start, current_end=cur.end, baseline_start=base.start).first()
        if diag is None or request.GET.get("refresh"):
            diag = analysis.run(ws.pk)
    except analysis.NoData as e:
        return render(request, "web/overview.html#diagnosis_empty", _ctx(request, message=str(e)))
    return render(request, "web/overview.html#diagnosis", _ctx(request, diag=diag, r=diag.result, causes=cause_cards(diag.result), chart=bridge(diag.result), channels=_channel_rows(diag.result)))


def _channel_rows(r: dict[str, Any]) -> list[dict[str, Any]]:
    units = r.get("decomposition", {}).get("units", {})
    metric = r["metric"]
    rows = []
    for ch, u in sorted(units.items(), key=lambda kv: -kv[1]["current"]["spend"]):
        b, c = u["baseline"][metric], u["current"][metric]
        rows.append({"channel": channel_label(ch), "spend": u["current"]["spend"], "before": b, "now": c, "change": (c / b - 1) * 100 if b and c else None})
    return rows


# --- ask --------------------------------------------------------------------------------------------


@workspace_view()
def ask(request: HttpRequest) -> HttpResponse:
    ws = request.workspace  # type: ignore[attr-defined]
    if request.method == "POST":
        if request.membership.role == "client":  # type: ignore[attr-defined]
            return HttpResponseForbidden("Client viewers read answers; asking is for the agency team.")
        text = (request.POST.get("question") or "").strip()
        if not text:
            return render(request, "web/ask.html#ask_error", _ctx(request, message="Write a question first."), status=422)
        q = assistant.ask(ws.pk, request.user, text)
        q.refresh_from_db()
        return render(request, "web/ask.html#question", _ctx(request, q=q, **_question_ctx(q)))
    recent = Question.objects.filter(workspace=ws)[:8]
    return render(request, "web/ask.html", _ctx(request, recent=recent, suggestions=SUGGESTIONS, section="ask"))


def _question_ctx(q: Question) -> dict[str, Any]:
    if q.status != Question.Status.ANSWERED:
        return {}
    diag = q.diagnosis
    r = diag.result if diag is not None else None
    props = engine.related(diag) if diag is not None and diag.material else []
    return {
        "segments": answer_segments(q.answer, q.numbers or []),
        "chart": bridge(r) if r else None,
        "r": r,
        "proposals": props,
        "naive": engine.naive_cuts(r) if r else {},
        "traced": sum(1 for n in q.numbers if n["traced"]),
        "untraced": sum(1 for n in q.numbers if not n["traced"]),
    }


@workspace_view()
def question(request: HttpRequest, pk: int) -> HttpResponse:
    q = get_object_or_404(Question, pk=pk, workspace=request.workspace)  # type: ignore[attr-defined]
    tpl = "web/ask.html#question" if _htmx(request) else "web/question_page.html"
    return render(request, tpl, _ctx(request, q=q, section="ask", **_question_ctx(q)))


@workspace_view(roles=("analyst", "manager"))
@require_POST
def retry_question(request: HttpRequest, pk: int) -> HttpResponse:
    q = get_object_or_404(Question, pk=pk, workspace=request.workspace)  # type: ignore[attr-defined]
    nq = assistant.ask(q.workspace_id, request.user, q.text)
    nq.refresh_from_db()
    return render(request, "web/ask.html#question", _ctx(request, q=nq, **_question_ctx(nq)))


# --- proposals -------------------------------------------------------------------------------------


@workspace_view()
def proposals(request: HttpRequest) -> HttpResponse:
    ws = request.workspace  # type: ignore[attr-defined]
    pending = list(Proposal.objects.filter(workspace=ws, status=Proposal.Status.PROPOSED).select_related("diagnosis").order_by("-created_at"))
    decided = list(Proposal.objects.filter(workspace=ws).exclude(status=Proposal.Status.PROPOSED).select_related("decided_by").order_by("-decided_at")[:30])
    items = pending + decided
    return render(request, "web/proposals.html", _ctx(request, items=items, section="proposals"))


@workspace_view(roles=("manager",))
@require_POST
def decide(request: HttpRequest, pk: int) -> HttpResponse:
    p = get_object_or_404(Proposal, pk=pk, workspace=request.workspace)  # type: ignore[attr-defined]
    try:
        engine.decide(p, request.user, request.POST.get("decision") == "approve", request.POST.get("note", ""), request.membership.role)  # type: ignore[attr-defined]
    except engine.NotAllowed as e:
        return render(request, "web/proposals.html#proposal", _ctx(request, p=p, error=str(e)), status=409)
    return render(request, "web/proposals.html#proposal", _ctx(request, p=p))


# --- data checks, connections, audit ------------------------------------------------------------------


@workspace_view()
def checks(request: HttpRequest) -> HttpResponse:
    ws = request.workspace  # type: ignore[attr-defined]
    diag = Diagnosis.objects.filter(workspace=ws).first()
    signals = diag.result.get("signals", []) if diag else []
    return render(request, "web/checks.html", _ctx(request, diag=diag, signals=signals, section="checks"))


@workspace_view()
def connections(request: HttpRequest) -> HttpResponse:
    ws = request.workspace  # type: ignore[attr-defined]
    accts = list(ConnectorAccount.objects.filter(workspace=ws).order_by("kind"))
    last = {a.pk: SyncRun.objects.filter(connector=a).first() for a in accts}
    rows = [{"a": a, "run": last[a.pk]} for a in accts]
    return render(request, "web/connections.html", _ctx(request, rows=rows, section="connections"))


@workspace_view(roles=("analyst", "manager"))
@require_POST
def sync_now(request: HttpRequest, pk: int) -> HttpResponse:
    a = get_object_or_404(ConnectorAccount, pk=pk, workspace=request.workspace)  # type: ignore[attr-defined]
    start, end = default_window(a)
    run = sync(a, start, end)
    return render(request, "web/connections.html#row", _ctx(request, row={"a": a, "run": run}))


@workspace_view()
def audit(request: HttpRequest) -> HttpResponse:
    ws = request.workspace  # type: ignore[attr-defined]
    events = list(AuditEvent.objects.filter(workspace=ws).select_related("actor").order_by("-id")[:100])
    ok, n = engine.verify_chain(ws.pk)
    return render(request, "web/audit.html", _ctx(request, events=events, chain_ok=ok, chain_n=n, section="audit"))
