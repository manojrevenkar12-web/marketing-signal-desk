"""Turn causes into proposals a manager approves or rejects. Nothing here touches an ad account.

Budget changes follow the cause, not the symptom. A channel whose CPA rose because GA4 lost its
conversions keeps its budget; a site-wide conversion drop changes no budget at all; invalid traffic
loses exactly its wasted spend. `naive_cuts` is what a CPA-threshold rule would do with the same
numbers, for comparison in the evals and on the proposals page.
"""

from __future__ import annotations

import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.utils import timezone

from msd.analysis.models import Diagnosis
from msd.conf import channel_label, read
from msd.proposals.models import AuditEvent, Proposal
from msd.tenancy.scope import workspace_scope


def _money(x: float) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _daily(units: dict[str, Any], ch: str, period_days: int) -> float:
    return float(units[ch]["current"]["spend"]) / period_days


def plan(result: dict[str, Any]) -> list[dict[str, Any]]:
    cfg = read("proposals")
    g = cfg["guardrails"]
    units = result.get("decomposition", {}).get("units", {})
    cur = result["periods"]["current"]
    from datetime import date

    days = (date.fromisoformat(cur["end"]) - date.fromisoformat(cur["start"])).days + 1
    metric = result.get("metric", "cpa")
    out: list[dict[str, Any]] = []
    for c in result.get("causes", []):
        a = cfg["actions"][c["type"]]
        label = channel_label(c.get("channel"))
        target = f"{c['campaign']} on {label}" if c.get("campaign") else label
        p: dict[str, Any] = {
            "kind": c["type"],
            "channel": c.get("channel") or "",
            "campaign": c.get("campaign") or "",
            "title": a["title"].format(channel=label, target=target),
            "budget_change_per_day": None,
            "rationale": {"cause": c},
        }
        budget = a["budget"]
        ch = c.get("channel")
        if budget == "shift_out" and ch in units:
            spend = _daily(units, ch, days)
            amount = min(spend * a["pct"] / 100, spend * g["max_budget_cut_pct"] / 100, max(0.0, spend - g["min_daily_budget"]))
            others = {u: v["current"][metric] for u, v in units.items() if u != ch and v["current"][metric] is not None}
            best = (min if metric == "cpa" else max)(others, key=lambda u: others[u]) if others else None
            p["budget_change_per_day"] = -round(amount, 2)
            p["rationale"].update(to_channel=best, to_channel_kpi=others.get(best) if best else None, current_daily_spend=round(spend, 2))
            p["action"] = f"Lower {label}'s daily budget by {amount:.2f} and add it to {channel_label(best)}." if best else f"Lower {label}'s daily budget by {amount:.2f}."
        elif budget == "cut_waste" and ch in units:
            waste = float(c["evidence"].get("excess_cost_eur") or 0.0) / days
            p["budget_change_per_day"] = -round(waste, 2)
            p["action"] = f"Exclude the placements or audiences sending the invalid clicks on {target}; that traffic cost about {waste:.2f} a day. Claim the invalid-click credit from the platform."
        elif budget == "revert_mix" and ch in units:
            ev = c["evidence"]
            base_spend = float(units[ch]["baseline"]["spend"])
            # baseline period length differs; compare per day
            bdays = (date.fromisoformat(result["periods"]["baseline"]["end"]) - date.fromisoformat(result["periods"]["baseline"]["start"])).days + 1
            extra = _daily(units, ch, days) - base_spend / bdays
            amount = max(0.0, min(extra * a["pct"] / 100, _daily(units, ch, days) * g["max_budget_cut_pct"] / 100))
            p["budget_change_per_day"] = -round(amount, 2)
            p["rationale"].update(back_to=ev.get("from_channel"), extra_daily_spend=round(extra, 2))
            p["action"] = f"Move {amount:.2f} a day back from {label} to {channel_label(ev.get('from_channel'))}, half of what was shifted, and compare the next week."
        elif budget == "hold":
            p["budget_change_per_day"] = 0
            p["action"] = "Do not cut this budget: the conversions are happening, GA4 is not recording them. Check the tag and consent setup on the landing pages, then re-read the week."
        else:
            p["action"] = a["title"].format(channel=label, target=target) + "."
        out.append(p)
    return out


def naive_cuts(result: dict[str, Any]) -> dict[str, float]:
    """Channel -> daily budget a CPA-threshold rule would cut (positive numbers)."""
    rule = read("proposals")["naive_rule"]
    units = result.get("decomposition", {}).get("units", {})
    if result.get("metric") != "cpa":
        return {}
    from datetime import date

    cur = result["periods"]["current"]
    days = (date.fromisoformat(cur["end"]) - date.fromisoformat(cur["start"])).days + 1
    out = {}
    for ch, v in units.items():
        b, c = v["baseline"]["cpa"], v["current"]["cpa"]
        if b and c and (c / b - 1) * 100 >= rule["cut_when_channel_cpa_up_pct"]:
            out[ch] = round(_daily(units, ch, days) * rule["cut_pct"] / 100, 2)
    return out


def create(diag: Diagnosis) -> list[Proposal]:
    """Create the diagnosis's proposals. A proposal still waiting for a decision about the same
    cause, target and week is reused, so asking twice does not ask the manager twice."""
    out: list[Proposal] = []
    with workspace_scope(diag.workspace_id):
        for p in plan(diag.result):
            same = Proposal.objects.filter(
                workspace_id=diag.workspace_id,
                status=Proposal.Status.PROPOSED,
                kind=p["kind"],
                channel=p["channel"],
                campaign=p["campaign"],
                diagnosis__current_start=diag.current_start,
                diagnosis__current_end=diag.current_end,
                diagnosis__metric=diag.metric,
            ).first()
            if same is not None:
                out.append(same)
                continue
            made = Proposal.objects.create(
                workspace_id=diag.workspace_id,
                diagnosis=diag,
                kind=p["kind"],
                channel=p["channel"],
                campaign=p["campaign"],
                title=p["title"][:200],
                action=p["action"],
                budget_change_per_day=_money(p["budget_change_per_day"]) if p["budget_change_per_day"] is not None else None,
                rationale=p["rationale"],
            )
            audit(diag.workspace_id, None, "proposal.created", f"proposal:{made.pk}", {"kind": made.kind, "budget_change_per_day": str(made.budget_change_per_day)})
            out.append(made)
    return out


def related(diag: Diagnosis) -> list[Proposal]:
    """The proposals that answer this diagnosis's causes (made by it or reused from the same week)."""
    keys = {(p["kind"], p["channel"], p["campaign"]) for p in plan(diag.result)}
    with workspace_scope(diag.workspace_id):
        found = Proposal.objects.filter(workspace_id=diag.workspace_id, diagnosis__current_start=diag.current_start, diagnosis__current_end=diag.current_end, diagnosis__metric=diag.metric).order_by(
            "created_at"
        )
        out: dict[tuple, Proposal] = {}
        for p in found:
            k = (p.kind, p.channel, p.campaign)
            if k in keys and (k not in out or p.status != Proposal.Status.PROPOSED):
                out[k] = p
    return list(out.values())


class NotAllowed(PermissionError):
    pass


def decide(p: Proposal, user: Any, approve: bool, note: str, role: str) -> Proposal:
    if role != "manager":
        raise NotAllowed("only a manager approves or rejects budget proposals")
    with workspace_scope(p.workspace_id):
        p.refresh_from_db()
        if p.status != Proposal.Status.PROPOSED:
            raise NotAllowed(f"this proposal was already {p.status}")
        p.status = Proposal.Status.APPROVED if approve else Proposal.Status.REJECTED
        p.decided_by, p.decided_at, p.decision_note = user, timezone.now(), note[:500]
        p.save()
        audit(p.workspace_id, user, f"proposal.{p.status}", f"proposal:{p.pk}", {"note": p.decision_note, "budget_change_per_day": str(p.budget_change_per_day)})
    return p


def audit(workspace_id: int, actor: Any, action: str, subject: str, data: dict[str, Any]) -> AuditEvent:
    """Append an event to the workspace's hash chain. Call inside workspace_scope."""
    last = AuditEvent.objects.filter(workspace_id=workspace_id).order_by("-id").values_list("hash", flat=True).first() or "0" * 64
    body = json.dumps({"prev": last, "actor": getattr(actor, "pk", None), "action": action, "subject": subject, "data": data}, sort_keys=True, default=str)
    return AuditEvent.objects.create(workspace_id=workspace_id, actor=actor, action=action, subject=subject, data=data, prev_hash=last, hash=hashlib.sha256(body.encode()).hexdigest())


def verify_chain(workspace_id: int) -> tuple[bool, int]:
    with workspace_scope(workspace_id):
        prev = "0" * 64
        n = 0
        for e in AuditEvent.objects.filter(workspace_id=workspace_id).order_by("id"):
            body = json.dumps({"prev": prev, "actor": e.actor_id, "action": e.action, "subject": e.subject, "data": e.data}, sort_keys=True, default=str)
            if e.prev_hash != prev or e.hash != hashlib.sha256(body.encode()).hexdigest():
                return False, n
            prev, n = e.hash, n + 1
    return True, n
