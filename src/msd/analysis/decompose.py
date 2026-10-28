"""Why a KPI moved between two periods: spend mix, auction prices (CPM), click-through (CTR),
conversion rate (CVR) and, for ROAS, order value (AOV), per channel or per campaign.

Shares come from `shapley` and add up to the change exactly. Rates are computed from period totals
(not averages of daily rates), so a quiet day weighs what it weighed in reality.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from msd.analysis.shapley import Attribution, shapley

Metric = Literal["cpa", "roas"]


@dataclass
class Totals:
    spend: float = 0.0
    impressions: float = 0.0
    clicks: float = 0.0
    conversions: float = 0.0
    revenue: float = 0.0

    def add(self, spend: float, impressions: float, clicks: float, conversions: float, revenue: float) -> None:
        self.spend += spend
        self.impressions += impressions
        self.clicks += clicks
        self.conversions += conversions
        self.revenue += revenue

    def cpm(self) -> float | None:
        return self.spend / self.impressions * 1000 if self.impressions else None

    def ctr(self) -> float | None:
        return self.clicks / self.impressions if self.impressions else None

    def cvr(self) -> float | None:
        return self.conversions / self.clicks if self.clicks else None

    def aov(self) -> float | None:
        return self.revenue / self.conversions if self.conversions else None

    def cpa(self) -> float | None:
        return self.spend / self.conversions if self.conversions else None

    def roas(self) -> float | None:
        return self.revenue / self.spend if self.spend else None

    def cpc(self) -> float | None:
        return self.spend / self.clicks if self.clicks else None


def kpi(t: Totals, metric: Metric) -> float | None:
    return t.cpa() if metric == "cpa" else t.roas()


@dataclass
class Decomposition:
    metric: Metric
    attribution: Attribution
    units: list[str]
    baseline: dict[str, Totals]
    current: dict[str, Totals]
    by_unit: dict[str, float] = field(default_factory=dict)  # unit -> summed share (mix excluded)
    by_driver: dict[str, float] = field(default_factory=dict)  # mix/cpm/ctr/cvr/aov -> summed share
    mix_by_unit: dict[str, float] = field(default_factory=dict)  # how the mix share splits (marginal view)

    def as_dict(self) -> dict:
        a = self.attribution
        return {
            "metric": self.metric,
            "baseline": a.baseline,
            "current": a.current,
            "change": a.change,
            "shares": a.shares,
            "by_unit": self.by_unit,
            "by_driver": self.by_driver,
            "units": {
                u: {
                    "baseline": _rates(self.baseline[u]),
                    "current": _rates(self.current[u]),
                }
                for u in self.units
            },
        }


def _rates(t: Totals) -> dict[str, float | None]:
    return {
        "spend": round(t.spend, 2),
        "impressions": t.impressions,
        "clicks": t.clicks,
        "conversions": round(t.conversions, 2),
        "revenue": round(t.revenue, 2),
        "cpm": t.cpm(),
        "ctr": t.ctr(),
        "cvr": t.cvr(),
        "aov": t.aov(),
        "cpa": t.cpa(),
        "roas": t.roas(),
        "cpc": t.cpc(),
    }


class NoConversions(ValueError):
    pass


def decompose(baseline: dict[str, Totals], current: dict[str, Totals], metric: Metric = "cpa") -> Decomposition:
    units = sorted(u for u in set(baseline) | set(current) if (baseline.get(u, Totals()).spend > 0 or current.get(u, Totals()).spend > 0))
    b = {u: baseline.get(u, Totals()) for u in units}
    c = {u: current.get(u, Totals()) for u in units}
    for name, side in (("baseline", b), ("current", c)):
        if sum(t.conversions for t in side.values()) <= 0:
            raise NoConversions(f"no conversions in the {name} period")
    drivers = ["cpm", "ctr", "cvr"] + (["aov"] if metric == "roas" else [])

    def factor(u: str, d: str) -> tuple[float, float]:
        get = {"cpm": Totals.cpm, "ctr": Totals.ctr, "cvr": Totals.cvr, "aov": Totals.aov}[d]
        vb, vc = get(b[u]), get(c[u])
        # a unit with no spend (or no clicks, or no conversions) in one period has no rate there;
        # it then carries no weight, so borrowing the other period's rate changes nothing
        if vb is None and vc is None:
            vb = vc = 0.0 if d != "cpm" else 1.0
        return (vb if vb is not None else vc), (vc if vc is not None else vb)  # type: ignore[return-value]

    players = ["mix"] + [f"{u}|{d}" for u in units for d in drivers]
    sb, sc = sum(t.spend for t in b.values()), sum(t.spend for t in c.values())
    wb = np.array([b[u].spend / sb if sb else 0.0 for u in units])
    wc = np.array([c[u].spend / sc if sc else 0.0 for u in units])
    fb = {d: np.array([factor(u, d)[0] for u in units]) for d in drivers}
    fc = {d: np.array([factor(u, d)[1] for u in units]) for d in drivers}

    def value(masks: np.ndarray) -> np.ndarray:
        w = np.where(masks[:, [0]], wc, wb)
        f = {}
        for k, d in enumerate(drivers):
            cols = [1 + i * len(drivers) + k for i in range(len(units))]
            f[d] = np.where(masks[:, cols], fc[d], fb[d])
        yield_per_euro = w * 1000.0 * f["ctr"] * f["cvr"] / f["cpm"]
        if metric == "roas":
            return (yield_per_euro * f["aov"]).sum(axis=1)
        denom = yield_per_euro.sum(axis=1)
        with np.errstate(divide="ignore"):
            return np.where(denom > 0, 1.0 / np.where(denom > 0, denom, 1.0), np.inf)

    base, cur, shares = shapley(players, value)
    att = Attribution(players, base, cur, shares)
    dec = Decomposition(metric, att, units, b, c)
    for p, s in shares.items():
        if p == "mix":
            dec.by_driver["mix"] = dec.by_driver.get("mix", 0.0) + s
            continue
        u, d = p.split("|")
        dec.by_unit[u] = dec.by_unit.get(u, 0.0) + s
        dec.by_driver[d] = dec.by_driver.get(d, 0.0) + s
    # which units' spend shares moved, and in which direction for the KPI (one-at-a-time view)
    for i, u in enumerate(units):
        w = wb.copy()
        w[i] = wc[i]
        w = w / w.sum() if w.sum() else w
        m = np.zeros((1, len(players)), dtype=bool)
        alt = value(m)[0]
        # recompute with only unit i's share moved (others rescaled)
        y = w * 1000.0 * fb["ctr"] * fb["cvr"] / fb["cpm"]
        v = (y * fb["aov"]).sum() if metric == "roas" else (1.0 / y.sum() if y.sum() > 0 else np.inf)
        dec.mix_by_unit[u] = float(v - alt)
    return dec
