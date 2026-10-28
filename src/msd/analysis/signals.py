"""Check the data before explaining it.

A CPA that rose because GA4 stopped recording one channel's purchases is a tracking problem, not a
performance problem, and cutting that channel's budget would be the wrong call. These checks look
for what makes the numbers untrustworthy:

- tracking_gap: GA4 records a smaller share of what the platform reports, while the platform's own
  conversion rate holds. Several channels at once points at the site's tag or consent banner.
- overreporting: the platform claims more conversions relative to GA4 than it used to (an
  attribution window or modelled conversions changed), while GA4's rate holds.
- invalid_traffic: one campaign's click-through jumps while its conversion rate collapses: clicks
  nobody meant to make. The excess clicks and their cost are estimated from the baseline CTR and CPC.
- missing_days: a source has no rows for days the others have.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date

from msd.analysis.dataset import Dataset, Period
from msd.conf import channel_label, read


@dataclass
class Signal:
    kind: str
    channel: str | None
    campaign: str | None
    severity: str  # info, warning, critical
    summary: str
    evidence: dict[str, float | str | None] = field(default_factory=dict)
    since: date | None = None

    def as_dict(self) -> dict:
        d = asdict(self)
        d["since"] = self.since.isoformat() if self.since else None
        return d


def _ratio(a: float, b: float) -> float | None:
    return a / b if b else None


def _pct(new: float | None, old: float | None) -> float | None:
    return (new / old - 1) * 100 if new is not None and old else None


def _since(ds: Dataset, cur: Period, channel: str, test) -> date | None:
    """First day of the current period from which the daily test holds on every day."""
    days = sorted({r.day for r in ds.rows if cur.has(r.day) and r.channel == channel})
    first = None
    for d in days:
        rows = [r for r in ds.rows if r.day == d and r.channel == channel]
        first = (first or d) if test(rows) else None
    return first


def check(ds: Dataset, base: Period, cur: Period) -> list[Signal]:
    cfg = read("analysis")["signals"]
    out: list[Signal] = []
    channels = sorted({r.channel for r in ds.rows if r.spend > 0})

    # missing days
    all_days = {d for days in ds.channels_with_data.values() for d in days if cur.has(d) or base.has(d)}
    for ch in channels:
        have = ds.channels_with_data.get(ch, set())
        missing = sorted(d for d in all_days if d not in have)
        if len(missing) >= cfg["missing_days"]["min_days"]:
            out.append(
                Signal(
                    "missing_days",
                    ch,
                    None,
                    "critical" if any(cur.has(d) for d in missing) else "warning",
                    f"{len(missing)} day(s) with no {channel_label(ch)} data",
                    {"days": len(missing), "first": missing[0].isoformat(), "last": missing[-1].isoformat()},
                    missing[0],
                )
            )

    tb, tc = ds.totals(base, "platform"), ds.totals(cur, "platform")
    gb, gc = ds.totals(base, "ga4"), ds.totals(cur, "ga4")
    gaps: list[Signal] = []
    for ch in channels:
        if ch not in tb or ch not in tc:
            continue
        rb, rc = _ratio(gb[ch].conversions, tb[ch].conversions), _ratio(gc[ch].conversions, tc[ch].conversions)
        p_cvr = _pct(tc[ch].cvr(), tb[ch].cvr())
        g_cvr = _pct(gc[ch].cvr(), gb[ch].cvr())
        if rb and rc is not None:
            drop = (1 - rc / rb) * 100
            t = cfg["tracking_gap"]
            if drop >= t["min_drop_pct"] and p_cvr is not None and abs(p_cvr) <= t["max_platform_cvr_change_pct"]:
                since = _since(ds, cur, ch, lambda rows, rb=rb: sum(r.ga4_conversions for r in rows) < (1 - drop / 200) * rb * sum(r.platform_conversions for r in rows))
                gaps.append(
                    Signal(
                        "tracking_gap",
                        ch,
                        None,
                        "critical",
                        f"GA4 records {drop:.0f}% fewer of {channel_label(ch)}'s conversions than before, while {channel_label(ch)}'s own conversion rate moved {p_cvr:+.1f}%",
                        {"ga4_share_before": round(rb, 3), "ga4_share_now": round(rc, 3), "drop_pct": round(drop, 1), "platform_cvr_change_pct": round(p_cvr, 1)},
                        since,
                    )
                )
            o = cfg["overreporting"]
            pr_b, pr_c = _ratio(tb[ch].conversions, gb[ch].conversions), _ratio(tc[ch].conversions, gc[ch].conversions)
            if pr_b and pr_c is not None:
                rise = (pr_c / pr_b - 1) * 100
                if rise >= o["min_rise_pct"] and g_cvr is not None and abs(g_cvr) <= o["max_ga4_cvr_change_pct"]:
                    out.append(
                        Signal(
                            "overreporting",
                            ch,
                            None,
                            "warning",
                            f"{channel_label(ch)} now claims {rise:.0f}% more conversions per GA4 conversion than before, while GA4's rate for {channel_label(ch)} held",
                            {"platform_per_ga4_before": round(pr_b, 3), "platform_per_ga4_now": round(pr_c, 3), "rise_pct": round(rise, 1), "ga4_cvr_change_pct": round(g_cvr, 1)},
                        )
                    )
    sitewide = cfg["tracking_gap"]["sitewide_channels"]
    if len(gaps) >= sitewide:
        drops = [float(s.evidence["drop_pct"] or 0) for s in gaps]
        out.append(
            Signal(
                "tracking_gap",
                None,
                None,
                "critical",
                f"GA4 records fewer conversions for {len(gaps)} channels at once: a site-wide tag or consent problem",
                {"channels": len(gaps), "drop_pct": round(sum(drops) / len(drops), 1)},
                min((s.since for s in gaps if s.since), default=None),
            )
        )
    out.extend(gaps)

    # invalid traffic, per campaign
    it = cfg["invalid_traffic"]
    for ch in channels:
        cb, cc = ds.totals(base, "platform", "campaign", ch), ds.totals(cur, "platform", "campaign", ch)
        for camp, c in cc.items():
            b = cb.get(camp)
            if not b or not b.ctr() or not b.cvr() or not c.ctr() or c.cvr() is None:
                continue
            ctr_r = c.ctr() / b.ctr()  # type: ignore[operator]
            cvr_r = c.cvr() / b.cvr()  # type: ignore[operator]
            click_r = (c.clicks / cur.days) / (b.clicks / base.days)
            # real creative gains bring conversions with the clicks (conversions per impression rise
            # with CTR); invalid clicks do not
            conv_per_imp_r = ctr_r * cvr_r
            converting = (conv_per_imp_r - 1) / (ctr_r - 1) if ctr_r > 1 else 1.0
            if ctr_r >= it["min_ctr_ratio"] and converting <= it["max_converting_share_of_extra_clicks"] and click_r >= it["min_click_ratio"]:
                expected = c.impressions * b.ctr()  # type: ignore[operator]
                excess = max(0.0, c.clicks - expected)
                cost = excess * (b.cpc() or 0.0)
                out.append(
                    Signal(
                        "invalid_traffic",
                        ch,
                        camp,
                        "critical",
                        f"{camp} on {channel_label(ch)}: click-through up {(ctr_r - 1) * 100:.0f}% while conversion rate fell {(1 - cvr_r) * 100:.0f}%",
                        {"ctr_change_pct": round((ctr_r - 1) * 100, 1), "cvr_change_pct": round((cvr_r - 1) * 100, 1), "excess_clicks": round(excess), "excess_cost_eur": round(cost, 2)},
                        _since(
                            ds,
                            cur,
                            ch,
                            lambda rows, camp=camp, b=b: (lambda t: t[1] > 0 and t[0] / t[1] > b.ctr() * (1 + (ctr_r - 1) / 2))(
                                (sum(r.clicks for r in rows if r.campaign == camp), sum(r.impressions for r in rows if r.campaign == camp))
                            ),
                        ),
                    )
                )
    return out
