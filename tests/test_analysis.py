"""The development scenarios, analysis only. (scenarios/heldout is never used here.)"""

from pathlib import Path

import pytest

from msd.analysis.dataset import Dataset
from msd.analysis.diagnose import diagnose
from msd.analysis.service import periods_for
from msd.evals.grade import grade
from msd.evals.robustness import dataset_from_world
from msd.sim.world import build, load_scenario
from tests.conftest import DEV

CASES = sorted(DEV.glob("*.yaml"))


@pytest.mark.parametrize("path", CASES, ids=[p.stem for p in CASES])
def test_dev_scenario(path: Path):
    s = load_scenario(path)
    ds = dataset_from_world(build(s))
    base, cur = periods_for(ds)
    d = diagnose(ds, base, cur, s.expect.metric, "ga4")
    g = grade(s, d)
    assert g["top_cause_right"], g
    assert g["cause_recall"] == 1 and g["false_causes"] == 0, g
    assert g["signals_found"] == g["signals_expected"] and g["false_signals"] == 0, g
    assert g["shapley_gap"] is None or g["shapley_gap"] < 1e-9


def test_a_tracking_break_is_not_called_a_performance_problem():
    s = load_scenario(DEV / "meta-tag-broken.yaml")
    ds = dataset_from_world(build(s))
    d = diagnose(ds, *periods_for(ds), "cpa", "ga4")
    assert [c["type"] for c in d["causes"]] == ["tracking_loss"]
    assert not any(c["type"] == "conversion_drop" for c in d["causes"])


def test_platform_numbers_see_the_attribution_change():
    s = load_scenario(DEV / "meta-attribution-change.yaml")
    ds = dataset_from_world(build(s))
    ga4 = diagnose(ds, *periods_for(ds), "cpa", "ga4")
    plat = diagnose(ds, *periods_for(ds), "cpa", "platform")
    assert ga4["causes"] == []
    assert plat["kpi"]["change_pct"] < -5  # Meta's own numbers say CPA improved
    assert any(s["kind"] == "overreporting" for s in plat["signals"])
    assert [c["type"] for c in plat["causes"]][:1] == ["platform_overreporting"]  # and the desk says why


def test_missing_days_are_left_out_on_both_sides():
    ad = [{"day": d, "channel": "a", "campaign": "c", "spend": 1, "impressions": 10, "clicks": 1, "conversions": 1, "revenue": 1} for d in (1, 2)]
    ad += [{"day": d, "channel": "b", "campaign": "c", "spend": 1, "impressions": 10, "clicks": 1, "conversions": 1, "revenue": 1} for d in (1, 2, 3)]
    ga = [{"day": d, "channel": ch, "campaign": "c", "conversions": 1, "revenue": 1} for d in (1, 2, 3) for ch in ("a", "b")]
    ds = Dataset.build(ad, ga)
    assert {(r.channel, r.day) for r in ds.rows} == {("a", 1), ("a", 2), ("b", 1), ("b", 2), ("b", 3)}
