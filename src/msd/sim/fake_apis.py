"""The ad platforms' and GA4's reporting APIs, served from a simulated world.

Each handler answers in the shape the real API documents: Google Ads `googleAds:search` (GAQL,
int64 as strings, cost in micros, page tokens), Meta Insights (strings, the same purchase under
three action types, cursor paging), Microsoft Advertising reporting (submit, poll, download a zipped
CSV with header and copyright lines), TikTok `report/integrated/get` (code 0, pages, at most 30 days
per daily request), and GA4 `runReport` (dimension and metric values as strings, offset paging,
organic rows mixed in).

`Faults` adds what production APIs do to integrations: a 429 with Retry-After, a 503, a missing day.
The connectors are tested against this and must come out with the same totals.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from msd.sim.world import TrueRow, World

TOKEN = "sim-token"


@dataclass
class Faults:
    rate_limit_first: bool = True  # first call to each host gets 429 Retry-After: 0
    server_error_once: bool = True  # second call to each host gets 503
    calls: dict[str, int] = field(default_factory=lambda: defaultdict(int))


def _between(text: str) -> tuple[date, date]:
    m = re.search(r"segments\.date BETWEEN '(\d{4}-\d{2}-\d{2})' AND '(\d{4}-\d{2}-\d{2})'", text)
    if not m:
        raise ValueError("query needs segments.date BETWEEN")
    return date.fromisoformat(m.group(1)), date.fromisoformat(m.group(2))


class FakeApis:
    def __init__(self, world: World, faults: Faults | None = None) -> None:
        self.world = world
        self.faults = faults or Faults(rate_limit_first=False, server_error_once=False)
        self.ms_reports: dict[str, tuple[date, date, int]] = {}

    def rows(self, channel: str, start: date, end: date) -> list[TrueRow]:
        missing = self.world.missing(channel)
        return [r for r in self.world.rows if r.channel == channel and start <= r.day <= end and r.day not in missing]

    # -- transport ---------------------------------------------------------------------------
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, req: httpx.Request) -> httpx.Response:
        host = req.url.host
        authorised = req.headers.get("authorization") == f"Bearer {TOKEN}" or req.headers.get("access-token") == TOKEN
        if not authorised and host != "download.api.bingads.microsoft.com":  # report downloads use a signed URL
            return httpx.Response(401, json={"error": {"message": "invalid credentials"}})
        self.faults.calls[host] += 1
        n = self.faults.calls[host]
        if self.faults.rate_limit_first and n == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"error": {"message": "rate limited"}})
        if self.faults.server_error_once and n == 2:
            return httpx.Response(503, json={"error": {"message": "backend unavailable"}})
        if host == "googleads.googleapis.com":
            return self.google_ads(req)
        if host == "graph.facebook.com":
            return self.meta(req)
        if host in ("reporting.api.bingads.microsoft.com", "download.api.bingads.microsoft.com"):
            return self.microsoft(req)
        if host == "business-api.tiktok.com":
            return self.tiktok(req)
        if host == "analyticsdata.googleapis.com":
            return self.ga4(req)
        return httpx.Response(404, json={"error": f"no fake API for {host}"})

    # -- Google Ads ---------------------------------------------------------------------------
    def google_ads(self, req: httpx.Request) -> httpx.Response:
        if not re.search(r"/v\d+/customers/\d+/googleAds:search$", req.url.path):
            return httpx.Response(404)
        if not req.headers.get("developer-token"):
            return httpx.Response(401, json={"error": {"status": "UNAUTHENTICATED", "message": "developer-token header missing"}})
        body = json.loads(req.content)
        start, end = _between(body["query"])
        rows = sorted(self.rows("google_ads", start, end), key=lambda r: (r.day, r.campaign_id))
        offset = int(body.get("pageToken") or 0)
        size = 50
        page = rows[offset : offset + size]
        out: dict = {
            "results": [
                {
                    "campaign": {"resourceName": f"customers/1234567890/campaigns/{r.campaign_id}", "id": r.campaign_id, "name": r.campaign},
                    "segments": {"date": r.day.isoformat()},
                    "metrics": {
                        "costMicros": str(round(r.spend * 1_000_000)),
                        "impressions": str(r.impressions),
                        "clicks": str(r.clicks),
                        "conversions": r.platform_conversions,
                        "conversionsValue": r.platform_revenue,
                    },
                }
                for r in page
            ],
            "fieldMask": "campaign.id,campaign.name,segments.date,metrics.costMicros,metrics.impressions,metrics.clicks,metrics.conversions,metrics.conversionsValue",
        }
        if offset + size < len(rows):
            out["nextPageToken"] = str(offset + size)
        return httpx.Response(200, json=out)

    # -- Meta ---------------------------------------------------------------------------------
    def meta(self, req: httpx.Request) -> httpx.Response:
        if not re.search(r"/v[\d.]+/act_\d+/insights$", req.url.path):
            return httpx.Response(404)
        q = parse_qs(urlparse(str(req.url)).query)
        tr = json.loads(q["time_range"][0])
        start, end = date.fromisoformat(tr["since"]), date.fromisoformat(tr["until"])
        if q.get("level") != ["campaign"] or q.get("time_increment") != ["1"]:
            return httpx.Response(400, json={"error": {"message": "expected level=campaign&time_increment=1", "code": 100}})
        rows = sorted(self.rows("meta", start, end), key=lambda r: (r.day, r.campaign_id))
        limit = int(q.get("limit", ["25"])[0])
        after = int(q.get("after", ["0"])[0])
        page = rows[after : after + limit]

        def actions(v: float) -> list[dict]:
            s = f"{v:.2f}".rstrip("0").rstrip(".")
            return [{"action_type": t, "value": s} for t in ("purchase", "omni_purchase", "offsite_conversion.fb_pixel_purchase")]

        data = [
            {
                "campaign_id": r.campaign_id,
                "campaign_name": r.campaign,
                "date_start": r.day.isoformat(),
                "date_stop": r.day.isoformat(),
                "spend": f"{r.spend:.2f}",
                "impressions": str(r.impressions),
                "clicks": str(r.clicks),
                "actions": actions(r.platform_conversions),
                "action_values": actions(r.platform_revenue),
            }
            for r in page
        ]
        out: dict = {"data": data, "paging": {"cursors": {"before": str(after), "after": str(after + len(page))}}}
        if after + limit < len(rows):
            nq = {k: v[0] for k, v in q.items()} | {"after": str(after + limit)}
            out["paging"]["next"] = f"https://graph.facebook.com{req.url.path}?{urlencode(nq)}"
        return httpx.Response(200, json=out)

    # -- Microsoft Advertising -----------------------------------------------------------------
    def microsoft(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path.endswith("/GenerateReport/Submit"):
            body = json.loads(req.content)
            rr = body["ReportRequest"]
            t = rr["Time"]
            s, e = t["CustomDateRangeStart"], t["CustomDateRangeEnd"]
            start, end = date(s["Year"], s["Month"], s["Day"]), date(e["Year"], e["Month"], e["Day"])
            rid = f"rep{len(self.ms_reports) + 1}"
            self.ms_reports[rid] = (start, end, 0)
            return httpx.Response(200, json={"ReportRequestId": rid})
        if path.endswith("/GenerateReport/Poll"):
            rid = json.loads(req.content)["ReportRequestId"]
            start, end, polls = self.ms_reports[rid]
            self.ms_reports[rid] = (start, end, polls + 1)
            if polls == 0:
                return httpx.Response(200, json={"ReportRequestStatus": {"Status": "Pending", "ReportDownloadUrl": None}})
            return httpx.Response(200, json={"ReportRequestStatus": {"Status": "Success", "ReportDownloadUrl": f"https://download.api.bingads.microsoft.com/ReportDownload/{rid}.zip"}})
        m = re.search(r"/ReportDownload/(rep\d+)\.zip$", path)
        if m:
            start, end, _ = self.ms_reports[m.group(1)]
            buf = io.StringIO()
            buf.write('"Report Name: Campaign performance"\n')
            buf.write(f'"Report Time: {start:%m/%d/%Y},{end:%m/%d/%Y}"\n')
            buf.write(f'"Time Zone: (GMT+01:00) Amsterdam, Berlin"\n"Last Completed Available Day: {datetime(2026, 9, 28):%m/%d/%Y %I:%M:%S %p}"\n"Rows: {{n}}"\n\n')
            w = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\n")
            w.writerow(["TimePeriod", "CampaignId", "CampaignName", "Impressions", "Clicks", "Spend", "Conversions", "Revenue"])
            rows = sorted(self.rows("microsoft_ads", start, end), key=lambda r: (r.day, r.campaign_id))
            for r in rows:
                w.writerow([f"{r.day:%m/%d/%Y}", r.campaign_id, r.campaign, f"{r.impressions:,}", r.clicks, f"{r.spend:.2f}", f"{r.platform_conversions:.2f}", f"{r.platform_revenue:.2f}"])
            buf.write('\n"©2026 Microsoft Corporation. All rights reserved. "\n')
            text = buf.getvalue().replace("{n}", str(len(rows)))
            z = io.BytesIO()
            with zipfile.ZipFile(z, "w") as zf:
                zf.writestr(f"{m.group(1)}.csv", "﻿" + text)
            return httpx.Response(200, content=z.getvalue(), headers={"Content-Type": "application/zip"})
        return httpx.Response(404)

    # -- TikTok -------------------------------------------------------------------------------
    def tiktok(self, req: httpx.Request) -> httpx.Response:
        if not req.url.path.endswith("/open_api/v1.3/report/integrated/get/"):
            return httpx.Response(404)
        q = dict(req.url.params)
        start, end = date.fromisoformat(q["start_date"]), date.fromisoformat(q["end_date"])
        if (end - start).days > 29:
            return httpx.Response(200, json={"code": 40002, "message": "The time span cannot exceed 30 days when stat_time_day is a dimension.", "data": {}})
        rows = sorted(self.rows("tiktok", start, end), key=lambda r: (r.day, r.campaign_id))
        page, size = int(q.get("page", 1)), int(q.get("page_size", 10))
        chunk = rows[(page - 1) * size : page * size]
        total_page = max(1, -(-len(rows) // size))
        return httpx.Response(
            200,
            json={
                "code": 0,
                "message": "OK",
                "request_id": f"sim-{page}",
                "data": {
                    "list": [
                        {
                            "dimensions": {"campaign_id": r.campaign_id, "stat_time_day": f"{r.day.isoformat()} 00:00:00"},
                            "metrics": {
                                "campaign_name": r.campaign,
                                "spend": f"{r.spend:.2f}",
                                "impressions": str(r.impressions),
                                "clicks": str(r.clicks),
                                "conversion": str(round(r.platform_conversions)),
                            },
                        }
                        for r in chunk
                    ],
                    "page_info": {"page": page, "page_size": size, "total_number": len(rows), "total_page": total_page},
                },
            },
        )

    # -- GA4 ----------------------------------------------------------------------------------
    def ga4(self, req: httpx.Request) -> httpx.Response:
        if not re.search(r"/v1beta/properties/\d+:runReport$", req.url.path):
            return httpx.Response(404)
        body = json.loads(req.content)
        dr = body["dateRanges"][0]
        start, end = date.fromisoformat(dr["startDate"]), date.fromisoformat(dr["endDate"])
        dims = [d["name"] for d in body["dimensions"]]
        mets = [m["name"] for m in body["metrics"]]
        if dims != ["date", "sessionSourceMedium", "sessionCampaignName"] or mets != ["keyEvents", "totalRevenue"]:
            return httpx.Response(400, json={"error": {"code": 400, "status": "INVALID_ARGUMENT", "message": f"unsupported request {dims} {mets}"}})
        agg: dict[tuple[str, str, str], list[float]] = defaultdict(lambda: [0, 0.0])
        for r in self.world.rows:
            if start <= r.day <= end:
                k = (r.day.strftime("%Y%m%d"), self.world.channels[r.channel].ga4_source_medium, r.campaign)
                agg[k][0] += r.ga4_conversions
                agg[k][1] += r.ga4_revenue
        for d, sm, n, rev in self.world.organic:
            if start <= d <= end:
                k = (d.strftime("%Y%m%d"), sm, "(not set)" if "organic" in sm or "direct" in sm else sm)
                agg[k][0] += n
                agg[k][1] += rev
        keys = sorted(agg)
        limit, offset = int(body.get("limit", 10000)), int(body.get("offset", 0))
        rows = [
            {"dimensionValues": [{"value": a}, {"value": b}, {"value": c}], "metricValues": [{"value": str(int(agg[(a, b, c)][0]))}, {"value": f"{agg[(a, b, c)][1]:.2f}"}]}
            for a, b, c in keys[offset : offset + limit]
        ]
        return httpx.Response(
            200,
            json={
                "dimensionHeaders": [{"name": n} for n in dims],
                "metricHeaders": [{"name": "keyEvents", "type": "TYPE_INTEGER"}, {"name": "totalRevenue", "type": "TYPE_CURRENCY"}],
                "rows": rows,
                "rowCount": len(keys),
                "metadata": {"currencyCode": "EUR", "timeZone": "Europe/Berlin"},
                "kind": "analyticsData#runReport",
            },
        )
