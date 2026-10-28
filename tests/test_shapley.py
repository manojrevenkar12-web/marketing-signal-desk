import numpy as np
import pytest

from msd.analysis.decompose import NoConversions, Totals, decompose
from msd.analysis.shapley import MAX_PLAYERS, shapley


def t(spend, imp, clicks, conv, rev=0.0):
    x = Totals()
    x.add(spend, imp, clicks, conv, rev)
    return x


def test_two_player_product_by_hand():
    # v = a * b; a: 1 -> 2, b: 1 -> 3. a = ((2-1) + (6-3)) / 2 = 2, b = ((3-1) + (6-2)) / 2 = 3
    def v(m):
        a = np.where(m[:, 0], 2.0, 1.0)
        b = np.where(m[:, 1], 3.0, 1.0)
        return a * b

    base, cur, s = shapley(["a", "b"], v)
    assert (base, cur) == (1.0, 6.0)
    assert s == pytest.approx({"a": 2.0, "b": 3.0})


def test_efficiency_symmetry_and_dummy():
    def v(m):
        return np.where(m[:, 0], 2.0, 1.0) + np.where(m[:, 1], 2.0, 1.0) + 0 * m[:, 2]

    base, cur, s = shapley(["x", "y", "unchanged"], v)
    assert sum(s.values()) == pytest.approx(cur - base)
    assert s["x"] == pytest.approx(s["y"])
    assert s["unchanged"] == pytest.approx(0.0)


def test_too_many_players():
    with pytest.raises(ValueError):
        shapley([str(i) for i in range(MAX_PLAYERS + 1)], lambda m: m.sum(axis=1))


def test_cpa_decomposition_adds_up_exactly_and_finds_the_driver():
    base = {"a": t(1000, 100_000, 2000, 50), "b": t(500, 50_000, 1000, 40)}
    cur = {"a": t(1000, 70_000, 1400, 35), "b": t(500, 50_000, 1000, 40)}  # a's CPM up ~43%
    d = decompose(base, cur, "cpa")
    a = d.attribution
    assert a.baseline == pytest.approx(1500 / 90)
    assert a.current == pytest.approx(1500 / 75)
    assert sum(a.shares.values()) == pytest.approx(a.change, abs=1e-12)
    assert max(a.shares, key=lambda k: a.shares[k]) == "a|cpm"
    assert abs(a.shares["b|cpm"]) < 1e-12 and abs(a.shares["mix"]) < 1e-12


def test_roas_and_a_channel_that_appears():
    base = {"a": t(1000, 100_000, 2000, 50, 3000)}
    cur = {"a": t(900, 90_000, 1800, 45, 2700), "new": t(100, 20_000, 100, 1, 50)}
    d = decompose(base, cur, "roas")
    assert sum(d.attribution.shares.values()) == pytest.approx(d.attribution.change, abs=1e-12)
    assert d.by_driver["mix"] < 0  # money moved to a channel that returns less


def test_no_conversions():
    with pytest.raises(NoConversions):
        decompose({"a": t(100, 1000, 10, 0)}, {"a": t(100, 1000, 10, 1)})
