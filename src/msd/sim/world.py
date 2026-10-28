"""A simulated advertiser with known truth, for tests, evals and the demo.

A scenario names a period and a list of events (an auction getting more expensive, a broken GA4
tag, bot clicks on one campaign, a budget moved between channels...). The world produces what
really happened each day per campaign, and from that what each platform *reports* and what GA4
*records*. The two differ the way they do in real accounts: platforms over-report their own
conversions, GA4 misses some (consent, ad blockers), and a broken tag or a change in attribution
moves one without the other.

Only `msd.sim` and `msd.evals` may import this module. The connectors only ever see API responses
built from it (`fake_apis`), and the analysis only sees normalised rows.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from msd.conf import ROOT

EventType = Literal[
    "cpm_spike",  # auction pressure: CPM up
    "ctr_drop",  # creative fatigue: CTR down
    "cvr_drop",  # real conversion-rate drop (landing page, checkout, offer)
    "tracking_loss",  # GA4 records fewer conversions; nothing changed for real
    "invalid_clicks",  # bots click a campaign: clicks and cost, no conversions
    "budget_shift",  # EUR per day moved from one channel to another
    "budget_change",  # a campaign's or channel's budget scaled
    "overreport",  # a platform starts claiming more conversions (attribution change)
    "aov_drop",  # average order value down (promotion)
    "missing_days",  # the platform's API returns nothing for these days
]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Event(Strict):
    type: EventType
    start: date = None  # type: ignore[assignment]  # required, except for missing_days (from its dates)
    end: date | None = None  # inclusive; None = until the end of the scenario
    channel: str | None = None  # None = every channel (where that makes sense)
    campaign: str | None = None  # campaign name within the channel
    pct: float | None = None  # size of the change in percent (positive = more of it)
    to_channel: str | None = None  # budget_shift
    eur_per_day: float | None = None  # budget_shift
    clicks_per_day: float | None = None  # invalid_clicks
    dates: list[date] = Field(default_factory=list)  # missing_days

    @model_validator(mode="after")
    def _needs(self) -> Event:
        if self.start is None:
            if self.type == "missing_days" and self.dates:
                self.start = min(self.dates)
            else:
                raise ValueError(f"{self.type} needs start")
        need: dict[str, tuple[str, ...]] = {
            "cpm_spike": ("pct", "channel"),
            "ctr_drop": ("pct", "channel"),
            "cvr_drop": ("pct",),
            "tracking_loss": ("pct",),
            "invalid_clicks": ("channel", "campaign", "clicks_per_day"),
            "budget_shift": ("channel", "to_channel", "eur_per_day"),
            "budget_change": ("channel", "pct"),
            "overreport": ("channel", "pct"),
            "aov_drop": ("pct",),
            "missing_days": ("channel", "dates"),
        }
        missing = [f for f in need[self.type] if not getattr(self, f)]
        if missing:
            raise ValueError(f"{self.type} needs {', '.join(missing)}")
        return self

    def active(self, d: date) -> bool:
        return d >= self.start and (self.end is None or d <= self.end)

    def hits(self, channel: str, campaign: str) -> bool:
        return (self.channel in (None, channel)) and (self.campaign in (None, campaign))


class TruthCause(Strict):
    type: str
    channel: str | None = None
    campaign: str | None = None


class TruthSignal(Strict):
    kind: str
    channel: str | None = None
    campaign: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _type_alias(cls, v: Any) -> Any:
        # the first writing guide did not name the key; "type" is accepted as well as "kind"
        if isinstance(v, dict) and "kind" not in v and "type" in v:
            v = {**v, "kind": v["type"]}
            v.pop("type")
        return v


class Expect(Strict):
    causes: list[TruthCause] = Field(default_factory=list)  # in order of importance; empty = no material change
    signals: list[TruthSignal] = Field(default_factory=list)  # data problems that must be raised; others are false alarms
    metric: Literal["cpa", "roas"] = "cpa"


class Scenario(Strict):
    id: str
    title: str = ""
    seed: int = 7
    start: date = date(2026, 8, 3)
    end: date = date(2026, 9, 27)  # inclusive
    question: str = "Why did our CPA change last week?"
    events: list[Event] = Field(default_factory=list)
    expect: Expect = Field(default_factory=Expect)
    note: str = ""


@dataclass
class Campaign:
    id: str
    name: str
    budget: float
    cpm: float
    ctr: float
    cvr: float


@dataclass
class ChannelSpec:
    name: str
    platform_overreport: float
    ga4_source_medium: str
    campaigns: list[Campaign]


@dataclass
class TrueRow:
    day: date
    channel: str
    campaign_id: str
    campaign: str
    spend: float
    impressions: int
    clicks: int
    invalid_clicks: int
    conversions: int  # what really happened
    revenue: float
    platform_conversions: float
    platform_revenue: float
    ga4_conversions: int
    ga4_revenue: float


@dataclass
class World:
    scenario: Scenario
    rows: list[TrueRow]
    organic: list[tuple[date, str, int, float]]  # GA4 rows for non-paid traffic
    channels: dict[str, ChannelSpec] = field(default_factory=dict)

    def missing(self, channel: str) -> set[date]:
        return {d for e in self.scenario.events if e.type == "missing_days" and e.channel == channel for d in e.dates}


@lru_cache
def world_config() -> dict[str, Any]:
    return yaml.safe_load((ROOT / "config" / "world.yaml").read_text())


def channel_specs() -> dict[str, ChannelSpec]:
    cfg = world_config()
    return {name: ChannelSpec(name, c["platform_overreport"], c["ga4_source_medium"], [Campaign(**k) for k in c["campaigns"]]) for name, c in cfg["channels"].items()}


def load_scenario(path: Path) -> Scenario:
    return Scenario.model_validate(yaml.safe_load(path.read_text()))


def _seed(*parts: object) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:12], 16)


def _days(s: Scenario) -> list[date]:
    n = (s.end - s.start).days + 1
    return [s.start + timedelta(days=i) for i in range(n)]


def build(s: Scenario) -> World:
    cfg = world_config()
    specs = channel_specs()
    known = {(ch, c.name) for ch, sp in specs.items() for c in sp.campaigns}
    for e in s.events:
        for ch in (e.channel, e.to_channel):
            if ch is not None and ch not in specs:
                raise ValueError(f"{s.id}: unknown channel {ch}")
        if e.campaign is not None and (e.channel, e.campaign) not in known:
            raise ValueError(f"{s.id}: unknown campaign {e.channel}/{e.campaign}")
    noise = cfg["noise"]
    rows: list[TrueRow] = []
    for ch, spec in specs.items():
        n_camp = len(spec.campaigns)
        for camp in spec.campaigns:
            rng = np.random.default_rng(_seed(s.seed, ch, camp.id))
            for d in _days(s):
                budget = camp.budget * cfg["weekday_factor"][d.weekday()]
                cpm, ctr, cvr = camp.cpm, camp.ctr, camp.cvr
                aov = cfg["aov_eur"]
                capture = cfg["ga4_capture"]
                over = spec.platform_overreport
                bots = 0.0
                for e in s.events:
                    if not e.active(d):
                        continue
                    pct = (e.pct or 0.0) / 100.0
                    if e.type == "cpm_spike" and e.hits(ch, camp.name):
                        cpm *= 1 + pct
                    elif e.type == "ctr_drop" and e.hits(ch, camp.name):
                        ctr *= 1 - pct
                    elif e.type == "cvr_drop" and e.hits(ch, camp.name):
                        cvr *= 1 - pct
                    elif e.type == "tracking_loss" and e.hits(ch, camp.name):
                        capture *= 1 - pct
                    elif e.type == "overreport" and e.hits(ch, camp.name):
                        over *= 1 + pct
                    elif e.type == "aov_drop" and e.hits(ch, camp.name):
                        aov *= 1 - pct
                    elif e.type == "budget_change" and e.hits(ch, camp.name):
                        budget *= 1 + pct
                    elif e.type == "budget_shift":
                        if e.channel == ch:
                            budget -= (e.eur_per_day or 0.0) / n_camp
                        elif e.to_channel == ch:
                            budget += (e.eur_per_day or 0.0) / n_camp
                    elif e.type == "invalid_clicks" and e.hits(ch, camp.name):
                        bots += e.clicks_per_day or 0.0
                budget = max(budget, 0.0)
                spend = budget * max(0.0, 1 + rng.normal(0, noise["spend_sd"]))
                w = lambda: max(0.2, 1 + rng.normal(0, noise["rate_sd"]))
                cpm_d, ctr_d, cvr_d = cpm * w(), min(0.9, ctr * w()), min(0.9, cvr * w())
                impressions = int(rng.poisson(spend / cpm_d * 1000)) if spend > 0 else 0
                clicks = int(rng.binomial(impressions, ctr_d)) if impressions else 0
                conv = int(rng.binomial(clicks, cvr_d)) if clicks else 0
                invalid = int(rng.poisson(bots)) if bots else 0
                if invalid:
                    cpc = spend / clicks if clicks else cpm_d / (1000 * ctr_d)
                    spend += invalid * cpc
                    impressions += int(invalid * 1.15)  # bots load the ad before clicking
                    clicks += invalid
                order_values = rng.lognormal(math.log(aov) - cfg["aov_sd"] ** 2 / 2, cfg["aov_sd"], conv) if conv else np.zeros(0)
                revenue = float(order_values.sum())
                ga4_conv = int(rng.binomial(conv, min(1.0, capture))) if conv else 0
                ga4_rev = float(order_values[:ga4_conv].sum()) if ga4_conv else 0.0
                rows.append(
                    TrueRow(
                        day=d,
                        channel=ch,
                        campaign_id=camp.id,
                        campaign=camp.name,
                        spend=round(spend, 2),
                        impressions=impressions,
                        clicks=clicks,
                        invalid_clicks=invalid,
                        conversions=conv,
                        revenue=round(revenue, 2),
                        platform_conversions=round(conv * over, 2),
                        platform_revenue=round(revenue * over, 2),
                        ga4_conversions=ga4_conv,
                        ga4_revenue=round(ga4_rev, 2),
                    )
                )
    organic: list[tuple[date, str, int, float]] = []
    rng = np.random.default_rng(_seed(s.seed, "organic"))
    for d in _days(s):
        for o in cfg["organic_ga4_rows"]:
            n = int(rng.poisson(o["conversions_per_day"]))
            organic.append((d, o["source_medium"], n, round(n * cfg["aov_eur"], 2)))
    return World(s, rows, organic, specs)
