"""The rows the analysis works on: one per day, channel and campaign, with what the platform
reports and what GA4 recorded for the same traffic side by side."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal

from msd.analysis.decompose import Totals

Source = Literal["ga4", "platform"]


@dataclass
class Day:
    day: date
    channel: str
    campaign: str
    spend: float = 0.0
    impressions: float = 0.0
    clicks: float = 0.0
    platform_conversions: float = 0.0
    platform_revenue: float = 0.0
    ga4_conversions: float = 0.0
    ga4_revenue: float = 0.0


@dataclass
class Period:
    start: date
    end: date  # inclusive

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def has(self, d: date) -> bool:
        return self.start <= d <= self.end

    def label(self) -> str:
        return f"{self.start:%d %b} to {self.end:%d %b %Y}"

    def as_dict(self) -> dict[str, str]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}


@dataclass
class Dataset:
    rows: list[Day]
    channels_with_data: dict[str, set[date]] = field(default_factory=dict)

    @classmethod
    def build(cls, ad_rows: Iterable[Mapping], ga4_rows: Iterable[Mapping]) -> Dataset:
        """ad_rows: day, channel, campaign, spend, impressions, clicks, conversions, revenue.
        ga4_rows: day, channel (paid only), campaign, conversions, revenue."""
        by_key: dict[tuple[date, str, str], Day] = {}
        seen: dict[str, set[date]] = {}
        for r in ad_rows:
            k = (r["day"], r["channel"], r["campaign"])
            d = by_key.setdefault(k, Day(*k))
            d.spend += float(r["spend"])
            d.impressions += float(r["impressions"])
            d.clicks += float(r["clicks"])
            d.platform_conversions += float(r["conversions"])
            d.platform_revenue += float(r["revenue"] or 0)
            seen.setdefault(r["channel"], set()).add(r["day"])
        for g in ga4_rows:
            if not g.get("channel"):
                continue
            k = (g["day"], g["channel"], g["campaign"])
            d = by_key.setdefault(k, Day(*k))
            d.ga4_conversions += float(g["conversions"])
            d.ga4_revenue += float(g["revenue"])
        # a day a platform returned nothing is left out for that channel on both sides, so GA4's
        # conversions for it are not divided by missing clicks
        ad_days = set().union(*seen.values()) if seen else set()
        keep = [d for d in by_key.values() if d.day not in ad_days or d.day in seen.get(d.channel, set())]
        return cls(sorted(keep, key=lambda x: (x.day, x.channel, x.campaign)), seen)

    @property
    def last_day(self) -> date:
        return max(r.day for r in self.rows)

    @property
    def first_day(self) -> date:
        return min(r.day for r in self.rows)

    def totals(self, period: Period, source: Source, unit: Literal["channel", "campaign"] = "channel", channel: str | None = None) -> dict[str, Totals]:
        out: dict[str, Totals] = {}
        for r in self.rows:
            if not period.has(r.day) or (channel and r.channel != channel):
                continue
            key = r.channel if unit == "channel" else r.campaign
            conv = r.ga4_conversions if source == "ga4" else r.platform_conversions
            rev = r.ga4_revenue if source == "ga4" else r.platform_revenue
            out.setdefault(key, Totals()).add(r.spend, r.impressions, r.clicks, conv, rev)
        return out


def default_periods(last_day: date, current_days: int, baseline_days: int) -> tuple[Period, Period]:
    cur = Period(last_day - timedelta(days=current_days - 1), last_day)
    base = Period(cur.start - timedelta(days=baseline_days), cur.start - timedelta(days=1))
    return base, cur
