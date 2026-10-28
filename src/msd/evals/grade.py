"""Grade a diagnosis against a scenario's truth. Only evals may see the truth."""

from __future__ import annotations

from typing import Any

from msd.sim.world import Scenario, TruthCause, TruthSignal


def _cause_match(t: TruthCause, c: dict[str, Any]) -> bool:
    if c["type"] != t.type:
        return False
    if t.channel is not None and c["channel"] != t.channel:
        return False
    return not (t.campaign is not None and c.get("campaign") not in (None, t.campaign))


def _signal_match(t: TruthSignal, s: dict[str, Any]) -> bool:
    return s["kind"] == t.kind and (t.channel is None or s["channel"] == t.channel) and (t.campaign is None or s.get("campaign") == t.campaign)


def grade(s: Scenario, diag: dict[str, Any]) -> dict[str, Any]:
    causes = diag.get("causes", [])
    truth = s.expect.causes
    if not truth:
        top_ok = not causes
        recall = 1.0
        false_causes = len(causes)
    else:
        top_ok = bool(causes) and _cause_match(truth[0], causes[0])
        hit = [any(_cause_match(t, c) for c in causes) for t in truth]
        recall = sum(hit) / len(truth)
        false_causes = sum(1 for c in causes if not any(_cause_match(t, c) for t in truth))
    campaign_named = None
    if truth and truth[0].campaign and causes and _cause_match(truth[0], causes[0]):
        campaign_named = causes[0].get("campaign") == truth[0].campaign
    sigs = diag.get("signals", [])
    sig_found = [any(_signal_match(t, x) for x in sigs) for t in s.expect.signals]
    false_signals = [x for x in sigs if not any(_signal_match(t, x) for t in s.expect.signals)]
    # a site-wide tracking signal brings per-channel ones with it: those are not false alarms
    if any(t.kind == "tracking_gap" and t.channel is None for t in s.expect.signals):
        false_signals = [x for x in false_signals if x["kind"] != "tracking_gap"]
    shapley_gap = None
    if "decomposition" in diag:
        d = diag["decomposition"]
        shapley_gap = abs(sum(d["shares"].values()) - d["change"])
    return {
        "id": s.id,
        "top_cause_right": top_ok,
        "cause_recall": recall,
        "false_causes": false_causes,
        "campaign_named": campaign_named,
        "signals_found": sum(sig_found),
        "signals_expected": len(s.expect.signals),
        "false_signals": len(false_signals),
        "false_signal_kinds": sorted({f"{x['kind']}:{x['channel']}" for x in false_signals}),
        "shapley_gap": shapley_gap,
        "got": [f"{c['type']}:{c['channel']}:{c.get('campaign')}" for c in causes],
        "want": [f"{t.type}:{t.channel}:{t.campaign}" for t in truth],
        "kpi_change_pct": diag.get("kpi", {}).get("change_pct"),
    }
