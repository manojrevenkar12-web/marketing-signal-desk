"""Pull a window of data from one source into the normalised tables, idempotently.

Re-running a window replaces it: platforms restate recent days (late conversions, invalid-click
credits), so a window is always fetched whole and replaces what was stored for it, in one transaction."""

from __future__ import annotations

import logging
import os
import time
from datetime import date

import httpx
from django.db import transaction
from django.utils import timezone

from msd.conf import ROOT
from msd.connectors.base import AdRow, Connector, ConnectorError, Credentials, Ga4Row, Http
from msd.connectors.models import ConnectorAccount, SyncRun
from msd.connectors.platforms import KINDS
from msd.metrics.models import AdDaily, Ga4Daily
from msd.tenancy.scope import workspace_scope

log = logging.getLogger("msd.sync")


def _credentials(acct: ConnectorAccount) -> Credentials:
    if acct.mode == "sim":
        from msd.sim.fake_apis import TOKEN

        return Credentials(TOKEN, acct.account_id, {"developer_token": "sim", "login_customer_id": acct.account_id})
    ref = acct.secret_ref.upper().replace("-", "_")
    token = os.environ.get(f"MSD_SECRET_{ref}", "")
    if not token:
        raise ConnectorError(f"no secret MSD_SECRET_{ref} for {acct}")
    extra = {k.removeprefix(f"MSD_SECRET_{ref}_").lower(): v for k, v in os.environ.items() if k.startswith(f"MSD_SECRET_{ref}_")}
    return Credentials(token, acct.account_id, extra)


def _transport(acct: ConnectorAccount) -> httpx.BaseTransport | None:
    if acct.mode != "sim":
        return None
    # a simulated account: the platform's API, answered from a scenario (see msd.sim.fake_apis)
    from msd.sim.fake_apis import FakeApis, Faults
    from msd.sim.world import build, load_scenario

    return FakeApis(build(load_scenario(ROOT / acct.scenario)), Faults()).transport()


def default_window(acct: ConnectorAccount) -> tuple[date, date]:
    """Live accounts: the last 56 complete days. Simulated ones: the scenario's whole range."""
    if acct.mode == "sim":
        from msd.sim.world import load_scenario

        s = load_scenario(ROOT / acct.scenario)
        return s.start, s.end
    from datetime import timedelta

    from django.utils import timezone

    end = timezone.localdate() - timedelta(days=1)
    return end - timedelta(days=55), end


def sync(acct: ConnectorAccount, start: date, end: date, transport: httpx.BaseTransport | None = None) -> SyncRun:
    with workspace_scope(acct.workspace_id):
        run = SyncRun.objects.create(workspace_id=acct.workspace_id, connector=acct, window_start=start, window_end=end)
    http = Http(transport or _transport(acct), sleep=(lambda s: None) if acct.mode == "sim" else time.sleep)
    try:
        connector: Connector = KINDS[acct.kind](_credentials(acct), http)  # type: ignore[assignment]
        rows = connector.fetch(start, end)
        with workspace_scope(acct.workspace_id), transaction.atomic():
            if acct.kind == "ga4":
                Ga4Daily.objects.filter(workspace_id=acct.workspace_id, day__range=(start, end)).delete()
                Ga4Daily.objects.bulk_create(_ga4(acct.workspace_id, rows))  # type: ignore[arg-type]
            else:
                AdDaily.objects.filter(workspace_id=acct.workspace_id, channel=acct.kind, day__range=(start, end)).delete()
                AdDaily.objects.bulk_create(_ads(acct.workspace_id, rows))  # type: ignore[arg-type]
            run.status, run.rows = "ok", len(rows)
    except ConnectorError as e:
        log.warning("sync %s failed: %s", acct, e)
        run.status, run.error = "failed", str(e)[:2000]
    run.attempts, run.retries, run.finished_at = http.attempts, http.retries, timezone.now()
    with workspace_scope(acct.workspace_id):
        run.save()
    return run


def _ads(ws: int, rows: list[AdRow]) -> list[AdDaily]:
    merged: dict[tuple, AdDaily] = {}
    for r in rows:
        k = (r.day, r.channel, r.campaign_id)
        m = merged.get(k)
        if m is None:
            merged[k] = AdDaily(
                workspace_id=ws,
                day=r.day,
                channel=r.channel,
                campaign_id=r.campaign_id,
                campaign=r.campaign,
                spend=r.spend,
                impressions=r.impressions,
                clicks=r.clicks,
                conversions=r.conversions,
                revenue=r.revenue,
            )
        else:  # the same campaign and day twice (overlapping pages, chunk edges): keep one
            merged[k] = m
    return list(merged.values())


def _ga4(ws: int, rows: list[Ga4Row]) -> list[Ga4Daily]:
    merged: dict[tuple, Ga4Daily] = {}
    for r in rows:
        k = (r.day, r.source_medium, r.campaign)
        if k in merged:
            merged[k].conversions += r.conversions
            merged[k].revenue += r.revenue
        else:
            merged[k] = Ga4Daily(workspace_id=ws, day=r.day, source_medium=r.source_medium, channel=r.channel, campaign=r.campaign, conversions=r.conversions, revenue=r.revenue)
    return list(merged.values())
