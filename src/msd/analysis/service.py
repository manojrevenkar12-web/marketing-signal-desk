"""Run a diagnosis for a workspace from the stored rows and keep the result."""

from __future__ import annotations

from datetime import date

from msd.analysis.dataset import Dataset, Period, Source, default_periods
from msd.analysis.decompose import Metric
from msd.analysis.diagnose import diagnose
from msd.analysis.models import Diagnosis
from msd.conf import read
from msd.metrics.models import AdDaily, Ga4Daily
from msd.tenancy.scope import workspace_scope


class NoData(ValueError):
    pass


def load(workspace_id: int, start: date | None = None, end: date | None = None) -> Dataset:
    with workspace_scope(workspace_id):
        ads = AdDaily.objects.filter(workspace_id=workspace_id)
        ga4 = Ga4Daily.objects.filter(workspace_id=workspace_id, channel__isnull=False)
        if start:
            ads, ga4 = ads.filter(day__gte=start), ga4.filter(day__gte=start)
        if end:
            ads, ga4 = ads.filter(day__lte=end), ga4.filter(day__lte=end)
        ad_rows = list(ads.values("day", "channel", "campaign", "spend", "impressions", "clicks", "conversions", "revenue"))
        ga4_rows = list(ga4.values("day", "channel", "campaign", "conversions", "revenue"))
    if not ad_rows:
        raise NoData("no advertising data yet: connect a source and sync it")
    return Dataset.build(ad_rows, ga4_rows)


def periods_for(ds: Dataset, current: tuple[date, date] | None = None, baseline: tuple[date, date] | None = None) -> tuple[Period, Period]:
    cfg = read("analysis")["periods"]
    if current is None:
        return default_periods(ds.last_day, cfg["default_current_days"], cfg["default_baseline_days"])
    cur = Period(*current)
    if baseline is None:
        from datetime import timedelta

        base = Period(cur.start - timedelta(days=cfg["default_baseline_days"]), cur.start - timedelta(days=1))
    else:
        base = Period(*baseline)
    return base, cur


def run(workspace_id: int, metric: Metric = "cpa", source: Source = "ga4", current: tuple[date, date] | None = None, baseline: tuple[date, date] | None = None) -> Diagnosis:
    ds = load(workspace_id)
    base, cur = periods_for(ds, current, baseline)
    if cur.end > ds.last_day or base.start < ds.first_day:
        raise NoData(f"data covers {ds.first_day:%d %b} to {ds.last_day:%d %b %Y}; the question needs {base.start:%d %b} to {cur.end:%d %b %Y}")
    result = diagnose(ds, base, cur, metric, source)
    with workspace_scope(workspace_id):
        return Diagnosis.objects.create(
            workspace_id=workspace_id,
            metric=metric,
            source=source,
            baseline_start=base.start,
            baseline_end=base.end,
            current_start=cur.start,
            current_end=cur.end,
            material=bool(result.get("material")),
            result=result,
        )
