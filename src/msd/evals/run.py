"""End-to-end evaluation: every scenario goes through the same path a customer's data does.

For each scenario a fresh workspace gets five simulated accounts (Google Ads, Meta, Microsoft Ads,
TikTok, GA4). Each is synced through its platform's API shape, with a 429 and a 503 on the way.
The scenario's question is then asked through the assistant (plan, diagnosis, proposals, written
answer, grounding check). The result is graded against the scenario's truth, which only this
module and msd.sim can read.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Any

from django.contrib.auth import get_user_model

from msd.assistant import service as assistant
from msd.assistant.models import Question
from msd.assistant.writers import SimWriter
from msd.conf import ROOT
from msd.connectors.models import ConnectorAccount
from msd.connectors.sync import sync
from msd.evals.grade import grade
from msd.metrics.models import AdDaily, Ga4Daily
from msd.proposals.engine import naive_cuts
from msd.proposals.models import Proposal
from msd.sim.world import build, load_scenario
from msd.tenancy.models import Agency, Membership, Workspace
from msd.tenancy.scope import workspace_scope

PERFORMANCE = {"auction_pressure", "creative_fatigue", "conversion_drop", "invalid_traffic", "budget_mix_shift"}
ACCOUNTS = {"google_ads": "1234567890", "meta": "1029384756", "microsoft_ads": "180012345", "tiktok": "7012345678901234567", "ga4": "312345678"}


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def setup_workspace(scenario_path: Path, slug: str, agency: Agency) -> Workspace:
    ws = Workspace.objects.create(agency=agency, name=slug, slug=slug)
    rel = str(scenario_path.resolve().relative_to(ROOT))
    with workspace_scope(ws.pk):
        for kind, acct in ACCOUNTS.items():
            ConnectorAccount.objects.create(workspace=ws, kind=kind, account_id=acct, mode="sim", scenario=rel)
    return ws


def run_scenario(path: Path, agency: Agency, user: Any) -> dict[str, Any]:
    s = load_scenario(path)
    world = build(s)
    ws = setup_workspace(path, f"eval-{s.id}"[:50], agency)
    Membership.objects.create(user=user, workspace=ws, role="manager")
    with workspace_scope(ws.pk):
        accounts = list(ConnectorAccount.objects.filter(workspace=ws))
    runs = [sync(a, s.start, s.end) for a in accounts]
    # reconciliation: what was stored equals what the platforms reported
    recon_ok = True
    with workspace_scope(ws.pk):
        for ch in ("google_ads", "meta", "microsoft_ads", "tiktok"):
            missing = world.missing(ch)
            want = round(sum(r.spend for r in world.rows if r.channel == ch and r.day not in missing), 2)
            got = float(sum(r.spend for r in AdDaily.objects.filter(workspace=ws, channel=ch)))
            recon_ok &= abs(want - got) < 0.01
        want_ga4 = sum(r.ga4_conversions for r in world.rows)
        got_ga4 = float(sum(r.conversions for r in Ga4Daily.objects.filter(workspace=ws, channel__isnull=False)))
        recon_ok &= abs(want_ga4 - got_ga4) < 0.01
    q = assistant.ask(ws.pk, user, s.question)
    with workspace_scope(ws.pk):
        q = Question.objects.get(pk=q.pk)
        props = list(Proposal.objects.filter(workspace=ws).values("kind", "channel", "budget_change_per_day"))
        diag = q.diagnosis.result if q.diagnosis is not None else {}
    g = grade(s, diag)
    truth_perf = {t.channel for t in s.expect.causes if t.type in PERFORMANCE and t.channel}
    ours_wrong = sum(-float(p["budget_change_per_day"]) for p in props if p["budget_change_per_day"] is not None and float(p["budget_change_per_day"]) < 0 and p["channel"] not in truth_perf)
    naive = naive_cuts(diag) if diag else {}
    naive_wrong = sum(v for ch, v in naive.items() if ch not in truth_perf)
    g.update(
        {
            "status": q.status,
            "error": q.error,
            "untraced_numbers_shipped": sum(1 for n in q.numbers if not n["traced"]),
            "corrections": q.corrections,
            "fallback": q.fallback,
            "answer": q.answer,
            "sync_ok": all(r.status == "ok" for r in runs),
            "sync_retries": sum(r.retries for r in runs),
            "reconciled": recon_ok,
            "proposals": len(props),
            "wrong_cuts_per_day": round(ours_wrong, 2),
            "naive_wrong_cuts_per_day": round(naive_wrong, 2),
            "metric_planned": (q.plan or {}).get("metric"),
            "metric_expected": s.expect.metric,
        }
    )
    return g


def run_suite(directory: Path, writer_rate: float = 0.3) -> dict[str, Any]:
    assistant.set_writer(SimWriter(derived_number_rate=writer_rate))
    agency, _ = Agency.objects.get_or_create(slug="eval-agency", defaults={"name": "Eval agency"})
    user, _ = get_user_model().objects.get_or_create(username="eval-runner")
    cases = [run_scenario(p, agency, user) for p in sorted(directory.glob("*.yaml"))]
    n = len(cases)
    tot: dict[str, Any] = defaultdict(float)
    for c in cases:
        tot["top_cause_right"] += c["top_cause_right"]
        tot["cause_recall"] += c["cause_recall"]
        tot["false_causes"] += c["false_causes"]
        tot["signals_found"] += c["signals_found"]
        tot["signals_expected"] += c["signals_expected"]
        tot["false_signals"] += c["false_signals"]
        tot["untraced_numbers_shipped"] += c["untraced_numbers_shipped"]
        tot["corrections"] += c["corrections"]
        tot["fallbacks"] += c["fallback"]
        tot["wrong_cuts_per_day"] += c["wrong_cuts_per_day"]
        tot["naive_wrong_cuts_per_day"] += c["naive_wrong_cuts_per_day"]
        tot["sync_retries"] += c["sync_retries"]
    summary = {
        "scenarios": n,
        "top_cause_right": int(tot["top_cause_right"]),
        "cause_recall": round(tot["cause_recall"] / n, 3) if n else 0,
        "false_causes": int(tot["false_causes"]),
        "signals_found": int(tot["signals_found"]),
        "signals_expected": int(tot["signals_expected"]),
        "false_signals": int(tot["false_signals"]),
        "untraced_numbers_shipped": int(tot["untraced_numbers_shipped"]),
        "grounding_corrections": int(tot["corrections"]),
        "template_fallbacks": int(tot["fallbacks"]),
        "wrong_budget_cuts_per_day": round(tot["wrong_cuts_per_day"], 2),
        "naive_rule_wrong_cuts_per_day": round(tot["naive_wrong_cuts_per_day"], 2),
        "sync_retries_absorbed": int(tot["sync_retries"]),
        "all_synced_and_reconciled": all(c["sync_ok"] and c["reconciled"] for c in cases),
        "metric_read_right": sum(c["metric_planned"] == c["metric_expected"] for c in cases),
        "max_shapley_gap": max((c["shapley_gap"] or 0.0) for c in cases) if cases else 0.0,
        "failed": [
            c["id"] for c in cases if not (c["top_cause_right"] and c["cause_recall"] == 1 and not c["false_causes"] and c["signals_found"] == c["signals_expected"] and not c["false_signals"])
        ],
    }
    return {"summary": summary, "cases": cases}
