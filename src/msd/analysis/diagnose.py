"""From two periods of data to a ranked list of causes, each with the numbers that support it.

Rules decide the causes; the language model only writes them up afterwards (see msd.assistant).
The steps:

1. Check the data (msd.analysis.signals).
2. Attribute the KPI change to mix, CPM, CTR, CVR (and AOV for ROAS) per channel (Shapley).
3. Measure each driver's normal week-to-week movement in the baseline, so a driver is only named
   when its change stands out from its own noise.
4. Map drivers to causes, letting the data checks overrule: a conversion-rate drop on a channel
   whose GA4 tag lost conversions is a tracking loss, not a performance problem; a click-through jump
   with collapsing conversions is invalid traffic, not a better creative.
5. Drill into campaigns where one campaign carries most of a channel's effect.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import timedelta

import numpy as np

from msd.analysis.dataset import Dataset, Period, Source
from msd.analysis.decompose import Decomposition, Metric, NoConversions, Totals, decompose, kpi
from msd.analysis.signals import Signal, check
from msd.conf import read

DRIVER_CAUSE = {"cpm": "auction_pressure", "ctr": "creative_fatigue", "cvr": "conversion_drop", "aov": "order_value_drop"}
CAUSE_TEXT = {
    "auction_pressure": "auctions got more expensive (CPM)",
    "creative_fatigue": "fewer people clicked the ads (CTR)",
    "conversion_drop": "fewer clicks turned into purchases (CVR)",
    "site_conversion_drop": "fewer clicks turned into purchases on every channel at once (site or offer)",
    "order_value_drop": "orders got smaller (AOV)",
    "tracking_loss": "GA4 stopped recording some conversions (tracking, not performance)",
    "invalid_traffic": "clicks that were never going to buy (invalid traffic)",
    "budget_mix_shift": "budget moved towards channels that convert worse",
    "platform_overreporting": "the platform counts more conversions than before (attribution)",
}


@dataclass
class Cause:
    type: str
    channel: str | None
    campaign: str | None
    share: float  # of the KPI change, in KPI units, signed like the change
    drivers: list[str]
    evidence: dict[str, float | str | None] = field(default_factory=dict)

    def as_dict(self, change: float) -> dict:
        return {
            "type": self.type,
            "channel": self.channel,
            "campaign": self.campaign,
            "share": round(self.share, 4),
            "share_of_change_pct": round(100 * self.share / change, 1) if change else None,
            "drivers": self.drivers,
            "text": CAUSE_TEXT[self.type],
            "evidence": self.evidence,
        }


def _blocks(base: Period, days: int) -> list[Period]:
    out = []
    end = base.end
    while (end - base.start).days + 1 >= days:
        out.append(Period(end - timedelta(days=days - 1), end))
        end = end - timedelta(days=days)
    return out


def _driver(t: Totals, d: str) -> float | None:
    return {"cpm": t.cpm, "ctr": t.ctr, "cvr": t.cvr, "aov": t.aov}[d]()


def noise_z(ds: Dataset, base: Period, cur: Period, source: Source, drivers: list[str]) -> dict[str, float]:
    """For each channel|driver: how many week-to-week standard deviations (in log terms) the
    current value sits from the baseline value. Infinite when the baseline has too few weeks."""
    cfg = read("analysis")["periods"]
    history = Period(ds.first_day, base.end)
    blocks = _blocks(history, cfg["noise_block_days"])
    tb, tc = ds.totals(base, source), ds.totals(cur, source)
    per_block = [ds.totals(b, source) for b in blocks]
    out: dict[str, float] = {}
    spend_b = sum(t.spend for t in tb.values())
    spend_c = sum(t.spend for t in tc.values())
    for ch in set(tb) | set(tc):
        for d in drivers:
            vb, vc = (_driver(tb[ch], d) if ch in tb else None), (_driver(tc[ch], d) if ch in tc else None)
            if not vb or not vc:
                out[f"{ch}|{d}"] = math.inf
                continue
            vals = [v for blk in per_block if ch in blk and (v := _driver(blk[ch], d))]
            sd = float(np.std(np.log(vals), ddof=1)) if len(vals) >= 3 else 0.0
            # counting noise: a rate measured on n events cannot be known better than 1/sqrt(n)
            n = {"cpm": tc[ch].impressions, "ctr": tc[ch].clicks, "cvr": tc[ch].conversions, "aov": tc[ch].conversions}[d]
            floor = max(1 / math.sqrt(n) if n > 0 else 1.0, cfg["min_noise_sd"])
            out[f"{ch}|{d}"] = abs(math.log(vc / vb)) / max(sd, floor) if len(vals) >= 3 else math.inf
        # spend share movement, for the mix
        sb = tb[ch].spend / spend_b if ch in tb and spend_b else 0.0
        sc = tc[ch].spend / spend_c if ch in tc and spend_c else 0.0
        shares = [blk[ch].spend / s for blk in per_block if ch in blk and (s := sum(t.spend for t in blk.values()))]
        sd = float(np.std(shares, ddof=1)) if len(shares) >= 3 else 0.0
        out[f"{ch}|share"] = abs(sc - sb) / max(sd, 0.005) if len(shares) >= 3 else math.inf
    return out


def _pct(new: float | None, old: float | None) -> float | None:
    return round((new / old - 1) * 100, 1) if new is not None and old else None


def _within_channel(ds: Dataset, base: Period, cur: Period, source: Source, metric: Metric, channel: str, drivers: list[str]) -> dict:
    """Decompose one channel's KPI by campaign. Says whether the channel's move came from its
    campaign mix (budget moved between its campaigns) and which campaign carries the effect."""
    try:
        d = decompose(ds.totals(base, source, "campaign", channel), ds.totals(cur, source, "campaign", channel), metric)
    except NoConversions:
        return {}
    total = d.attribution.change
    if not total:
        return {}
    per: dict[str, float] = {}
    for p, s in d.attribution.shares.items():
        if p == "mix":
            continue
        u, drv = p.split("|")
        if drv in drivers:
            per[u] = per.get(u, 0.0) + s
    out: dict = {"mix_share": d.attribution.shares.get("mix", 0.0) / total}
    rates = sum(per.values())
    if per and rates:
        top = max(per, key=lambda u: per[u] * math.copysign(1, rates))
        out["top_campaign"], out["top_share"] = top, per[top] / rates
    return out


def diagnose(ds: Dataset, base: Period, cur: Period, metric: Metric = "cpa", source: Source = "ga4") -> dict:
    cfg = read("analysis")["materiality"]
    signals = check(ds, base, cur)
    tb, tc = ds.totals(base, source), ds.totals(cur, source)
    all_b, all_c = Totals(), Totals()
    for t in tb.values():
        all_b.add(t.spend, t.impressions, t.clicks, t.conversions, t.revenue)
    for t in tc.values():
        all_c.add(t.spend, t.impressions, t.clicks, t.conversions, t.revenue)
    out: dict = {
        "metric": metric,
        "source": source,
        "periods": {"baseline": base.as_dict(), "current": cur.as_dict()},
        "signals": [s.as_dict() for s in signals],
        "totals": {
            "baseline": {"spend": round(all_b.spend, 2), "conversions": round(all_b.conversions, 1), "per_day_spend": round(all_b.spend / base.days, 2)},
            "current": {"spend": round(all_c.spend, 2), "conversions": round(all_c.conversions, 1), "per_day_spend": round(all_c.spend / cur.days, 2)},
        },
        "causes": [],
    }
    try:
        dec = decompose(tb, tc, metric)
    except NoConversions as e:
        out.update(material=False, error=str(e))
        return out
    a = dec.attribution
    change_pct = (a.current / a.baseline - 1) * 100 if a.baseline else math.inf
    out["kpi"] = {"baseline": round(a.baseline, 4), "current": round(a.current, 4), "change": round(a.change, 4), "change_pct": round(change_pct, 1)}
    out["decomposition"] = dec.as_dict()
    drivers = ["cpm", "ctr", "cvr"] + (["aov"] if metric == "roas" else [])
    z = noise_z(ds, base, cur, source, drivers)
    out["noise_z"] = {k: (round(v, 2) if math.isfinite(v) else None) for k, v in z.items()}
    net_material = abs(change_pct) >= cfg["min_change_pct"]
    causes = _causes(ds, base, cur, metric, source, dec, z, signals, net_material)
    causes.sort(key=lambda c: -abs(c.share))
    out["causes"] = [c.as_dict(a.change) for c in causes[: cfg["max_causes"]]]
    out["material"] = net_material or bool(causes)
    # drivers that moved the KPI a lot but were hidden by others moving the other way
    out["offsetting"] = not net_material and bool(causes)
    return out


def _causes(ds: Dataset, base: Period, cur: Period, metric: Metric, source: Source, dec: Decomposition, z: dict[str, float], signals: list[Signal], net_material: bool) -> list[Cause]:
    cfg = read("analysis")["materiality"]
    sig_cfg = read("analysis")["signals"]
    drill = read("analysis")["drilldown"]["campaign_share"]
    a = dec.attribution
    direction = math.copysign(1.0, a.change)
    # a driver is named when it explains enough of the move, and moved the KPI enough on its own
    effect_floor = cfg["min_driver_effect_pct"] / 100 * abs(a.baseline)
    floor = max(cfg["min_share_of_change"] * abs(a.change), effect_floor) if net_material else effect_floor

    def pushes(s: float) -> bool:
        # when the KPI barely moved, a large driver hidden by others moving the other way still counts
        return s * direction > 0 if net_material else True

    def significant(ch: str, d: str) -> bool:
        return z.get(f"{ch}|{d}", math.inf) >= cfg["min_noise_z"]

    by: dict[tuple[str, str], float] = {}
    for p, s in a.shares.items():
        if p != "mix":
            u, d = p.split("|")
            by[(u, d)] = s
    sig = {(s.kind, s.channel): s for s in signals}
    invalid = {s.channel: s for s in signals if s.kind == "invalid_traffic"}
    gap_channels = {s.channel for s in signals if s.kind == "tracking_gap" and s.channel}
    sitewide_gap = ("tracking_gap", None) in sig
    found: list[Cause] = []
    folded_mix = 0.0  # within-channel campaign mix, reported with the channel mix

    # site-wide patterns first: the same driver moving on enough channels at once is one cause
    # (the site, the offer or the checkout), tested on the pooled rate so small channels count
    sitewide_n = sig_cfg["tracking_gap"]["sitewide_channels"]
    move = cfg["sitewide_min_move_pct"] / 100
    for d, kind, need in (("cvr", "site_conversion_drop", sitewide_n), ("aov", "order_value_drop", 2)):
        if d == "cvr" and sitewide_gap and source == "ga4":
            continue
        pool = [ch for ch in dec.units if (ch, d) in by and ch not in invalid and ch not in gap_channels]
        share = sum(by[(ch, d)] for ch in pool)
        sign = math.copysign(1.0, share)
        moved = []
        for ch in pool:
            vb, vc = _driver(dec.baseline[ch], d), _driver(dec.current[ch], d)
            if vb and vc is not None:
                # CVR and AOV hurt the KPI when they fall; for CPA that is a positive share
                rel = vc / vb - 1
                if abs(rel) >= move and math.copysign(1.0, by[(ch, d)]) == sign:
                    moved.append((ch, round(rel * 100, 1)))
        pb, pc = Totals(), Totals()
        for ch in pool:
            pb.add(*_tuple(dec.baseline[ch]))
            pc.add(*_tuple(dec.current[ch]))
        vb, vc = _driver(pb, d), _driver(pc, d)
        n = pc.conversions
        pooled_z = abs(math.log(vc / vb)) / max(1 / math.sqrt(n) if n else 1.0, read("analysis")["periods"]["min_noise_sd"]) if vb and vc else 0.0
        if len(moved) >= need and pooled_z >= cfg["min_noise_z"] and pushes(share) and abs(share) >= floor:
            found.append(Cause(kind, None, None, share, [d], {"channels": len(moved), "pooled_change_pct": _pct(vc, vb), **{f"{ch}_{d}_change_pct": r for ch, r in moved}}))
            for ch in pool:
                by.pop((ch, d), None)
    if sitewide_gap and source == "ga4":
        share = sum(by.pop((ch, "cvr"), 0.0) for ch in dec.units if ch not in invalid)
        if pushes(share) and abs(share) >= floor:
            found.append(Cause("tracking_loss", None, None, share, ["cvr"], dict(sig[("tracking_gap", None)].evidence)))

    for ch in dec.units:
        b, c = dec.baseline[ch], dec.current[ch]
        ev_base: dict[str, float | str | None] = {"channel_kpi_before": _r(kpi(b, metric)), "channel_kpi_now": _r(kpi(c, metric))}
        if ch in invalid:
            sg = invalid[ch]
            share = dec.by_unit.get(ch, 0.0)
            if pushes(share):
                found.append(Cause("invalid_traffic", ch, sg.campaign, share, ["ctr", "cvr"], {**ev_base, **sg.evidence}))
            continue
        for d in [x for x in ("cpm", "ctr", "cvr", "aov") if (ch, x) in by]:
            s = by[(ch, d)]
            if not pushes(s) or abs(s) < floor or not significant(ch, d):
                continue
            ev: dict[str, float | str | None] = {**ev_base, f"{d}_before": _r(_driver_val(b, d)), f"{d}_now": _r(_driver_val(c, d)), f"{d}_change_pct": _pct(_driver_val(c, d), _driver_val(b, d))}
            kind = DRIVER_CAUSE[d]
            if d == "cvr" and source == "ga4" and ch in gap_channels:
                found.append(Cause("tracking_loss", ch, None, s, [d], {**ev, **sig[("tracking_gap", ch)].evidence}))
                continue
            if d == "cvr" and source == "platform" and ("overreporting", ch) in sig:
                found.append(Cause("platform_overreporting", ch, None, s, [d], {**ev, **sig[("overreporting", ch)].evidence}))
                continue
            w = _within_channel(ds, base, cur, source, metric, ch, [d])
            if w.get("mix_share", 0.0) >= drill:
                folded_mix += s  # the channel's rate moved because budget moved between its campaigns
                continue
            camp = w.get("top_campaign") if w.get("top_share", 0.0) >= drill else None
            if camp:
                ev["campaign_share_of_channel_effect"] = round(w["top_share"], 3)
            found.append(Cause(kind, ch, camp, s, [d], ev))

    mix = a.shares.get("mix", 0.0) + folded_mix
    if pushes(mix) and abs(mix) >= floor:
        tot_b, tot_c = sum(t.spend for t in dec.baseline.values()), sum(t.spend for t in dec.current.values())
        moves = {ch: dec.current[ch].spend / tot_c - dec.baseline[ch].spend / tot_b for ch in dec.units}
        gainer, loser = max(moves, key=lambda k: moves[k]), min(moves, key=lambda k: moves[k])
        inv = next((f for f in found if f.type == "invalid_traffic" and f.channel == gainer), None)
        extra = (dec.current[gainer].spend / cur.days) - (dec.baseline[gainer].spend / base.days)
        if inv is not None and extra > 0 and float(invalid[gainer].evidence.get("excess_cost_eur") or 0) / cur.days >= 0.5 * extra:
            inv.share += mix  # the bots' cost is what grew this channel's share
        elif folded_mix or significant(gainer, "share"):
            found.append(
                Cause(
                    "budget_mix_shift",
                    gainer,
                    None,
                    mix,
                    ["mix"],
                    {
                        "to_channel": gainer,
                        "from_channel": loser,
                        "to_share_change_pts": round(100 * moves[gainer], 1),
                        "from_share_change_pts": round(100 * moves[loser], 1),
                        "to_channel_kpi": _r(kpi(dec.current[gainer], metric)),
                        "from_channel_kpi": _r(kpi(dec.current[loser], metric)),
                    },
                )
            )
    return [f for f in found if abs(f.share) >= floor]


def _tuple(t: Totals) -> tuple[float, float, float, float, float]:
    return t.spend, t.impressions, t.clicks, t.conversions, t.revenue


def _driver_val(t: Totals, d: str) -> float | None:
    v = _driver(t, d)
    if v is None:
        return None
    return v * 100 if d in ("ctr", "cvr") else v  # rates as percentages


def _r(v: float | None) -> float | None:
    return round(v, 2) if v is not None and math.isfinite(v) else None
