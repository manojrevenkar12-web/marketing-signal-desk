"""The development scenarios again with other random seeds, analysis only (no database): does the
diagnosis hold when the noise is different from the noise it was tuned on?"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from msd.analysis.dataset import Dataset
from msd.analysis.diagnose import diagnose
from msd.analysis.service import periods_for
from msd.evals.grade import grade
from msd.sim.world import build, load_scenario


def dataset_from_world(w: Any) -> Dataset:
    miss = {ch: w.missing(ch) for ch in w.channels}
    ad = [
        {
            "day": r.day,
            "channel": r.channel,
            "campaign": r.campaign,
            "spend": r.spend,
            "impressions": r.impressions,
            "clicks": r.clicks,
            "conversions": r.platform_conversions,
            "revenue": r.platform_revenue,
        }
        for r in w.rows
        if r.day not in miss[r.channel]
    ]
    ga = [{"day": r.day, "channel": r.channel, "campaign": r.campaign, "conversions": r.ga4_conversions, "revenue": r.ga4_revenue} for r in w.rows]
    return Dataset.build(ad, ga)


def run(directory: Path, seeds: int = 10, first_seed: int = 100) -> dict[str, Any]:
    per: dict[str, list[bool]] = {}
    for p in sorted(directory.glob("*.yaml")):
        s0 = load_scenario(p)
        for seed in range(first_seed, first_seed + seeds):
            s = s0.model_copy(update={"seed": seed})
            ds = dataset_from_world(build(s))
            base, cur = periods_for(ds)
            g = grade(s, diagnose(ds, base, cur, s.expect.metric, "ga4"))
            ok = g["top_cause_right"] and g["cause_recall"] == 1 and not g["false_causes"] and g["signals_found"] == g["signals_expected"] and not g["false_signals"]
            per.setdefault(s.id, []).append(bool(ok))
    total = sum(len(v) for v in per.values())
    right = sum(sum(v) for v in per.values())
    return {"summary": {"runs": total, "fully_right": right, "rate": round(right / total, 3) if total else 0.0, "seeds": seeds}, "by_scenario": {k: f"{sum(v)}/{len(v)}" for k, v in per.items()}}
