"""Exact Shapley attribution of a KPI change to its drivers.

CPA across channels is spend over conversions. Written per channel it depends only on the spend
mix and each channel's CPM, CTR and CVR:

    conversions_i = spend_i / CPM_i * 1000 * CTR_i * CVR_i
    CPA = 1 / sum_i ( w_i * 1000 * CTR_i * CVR_i / CPM_i ),   w_i = spend_i / total spend

ROAS adds each channel's order value:  ROAS = sum_i ( w_i * 1000 * CTR_i * CVR_i * AOV_i / CPM_i ).

Moving every driver from the baseline to the current period at once gives the total change, but
the order in which they move changes how much each one seems to explain (the drivers multiply).
The Shapley value averages over every order, so each driver gets one fair share and the shares add
up to the total change exactly. With the mix plus three or four drivers per channel there are at
most 17 players, so the 2^n coalitions are evaluated exactly in numpy, without sampling.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

MAX_PLAYERS = 18


@dataclass(frozen=True)
class Attribution:
    players: list[str]
    baseline: float
    current: float
    shares: dict[str, float]  # sums to current - baseline

    @property
    def change(self) -> float:
        return self.current - self.baseline


def shapley(players: Sequence[str], value: Callable[[np.ndarray], np.ndarray]) -> tuple[float, float, dict[str, float]]:
    """`value(masks)` takes a (k, n) boolean array, True meaning the player is at its current value,
    and returns k KPI values. Returns baseline, current and each player's share."""
    n = len(players)
    if n == 0:
        raise ValueError("no players")
    if n > MAX_PLAYERS:
        raise ValueError(f"{n} players is too many for exact Shapley (max {MAX_PLAYERS})")
    k = 1 << n
    idx = np.arange(k, dtype=np.int64)
    masks = ((idx[:, None] >> np.arange(n)) & 1).astype(bool)
    v = np.asarray(value(masks), dtype=float)
    size = masks.sum(axis=1)
    weight_by_size = np.array([math.factorial(s) * math.factorial(n - s - 1) / math.factorial(n) for s in range(n)])
    shares: dict[str, float] = {}
    for j, p in enumerate(players):
        without = idx[~masks[:, j]]
        with_j = without | (1 << j)
        shares[p] = float(np.sum(weight_by_size[size[without]] * (v[with_j] - v[without])))
    return float(v[0]), float(v[k - 1]), shares
