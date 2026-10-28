"""The four ad platforms and GA4, each in the shape its reporting API documents."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import date, datetime, timedelta
from decimal import Decimal

from msd.conf import read
from msd.connectors.base import AdRow, ConnectorError, Credentials, Ga4Row, Http, dec


def _chunks(start: date, end: date, days: int) -> list[tuple[date, date]]:
    out = []
    s = start
    while s <= end:
        e = min(end, s + timedelta(days=days - 1))
        out.append((s, e))
        s = e + timedelta(days=1)
    return out


class GoogleAds:
    channel = "google_ads"

    def __init__(self, creds: Credentials, http: Http) -> None:
        self.creds, self.http = creds, http
        self.cfg = read("channels")["channels"]["google_ads"]

    def fetch(self, start: date, end: date) -> list[AdRow]:
        url = f"https://googleads.googleapis.com/{self.cfg['api_version']}/customers/{self.creds.account_id}/googleAds:search"
        query = (
            "SELECT campaign.id, campaign.name, segments.date, metrics.cost_micros, metrics.impressions, "
            "metrics.clicks, metrics.conversions, metrics.conversions_value FROM campaign "
            f"WHERE segments.date BETWEEN '{start.isoformat()}' AND '{end.isoformat()}'"
        )
        headers = {"Authorization": f"Bearer {self.creds.token}", "developer-token": self.creds.extra.get("developer_token", ""), "login-customer-id": self.creds.extra.get("login_customer_id", "")}
        rows: list[AdRow] = []
        token = ""
        while True:
            body: dict = {"query": query} | ({"pageToken": token} if token else {})
            data = self.http.request("POST", url, json=body, headers=headers).json()
            for r in data.get("results", []):
                m = r["metrics"]
                rows.append(
                    AdRow(
                        day=date.fromisoformat(r["segments"]["date"]),
                        channel=self.channel,
                        campaign_id=str(r["campaign"]["id"]),
                        campaign=r["campaign"]["name"],
                        spend=(dec(m.get("costMicros")) / Decimal(1_000_000)).quantize(Decimal("0.01")),
                        impressions=int(m.get("impressions", 0)),
                        clicks=int(m.get("clicks", 0)),
                        conversions=dec(m.get("conversions")),
                        revenue=dec(m.get("conversionsValue")),
                    )
                )
            token = data.get("nextPageToken", "")
            if not token:
                return rows


class Meta:
    channel = "meta"

    def __init__(self, creds: Credentials, http: Http) -> None:
        self.creds, self.http = creds, http
        self.cfg = read("channels")["channels"]["meta"]

    def _action(self, actions: list[dict] | None) -> Decimal:
        # pick the one configured action type; summing all purchase types would count each purchase three times
        want = self.cfg["conversion_action"]
        return next((dec(a["value"]) for a in actions or [] if a.get("action_type") == want), Decimal(0))

    def fetch(self, start: date, end: date) -> list[AdRow]:
        params = {
            "level": "campaign",
            "time_increment": "1",
            "time_range": json.dumps({"since": start.isoformat(), "until": end.isoformat()}),
            "fields": "campaign_id,campaign_name,spend,impressions,clicks,actions,action_values",
            "limit": "50",
        }
        url: str | None = f"https://graph.facebook.com/{self.cfg['api_version']}/act_{self.creds.account_id}/insights"
        headers = {"Authorization": f"Bearer {self.creds.token}"}
        rows: list[AdRow] = []
        first = True
        while url:
            data = self.http.request("GET", url, params=params if first else None, headers=headers).json()
            first = False
            for r in data.get("data", []):
                rows.append(
                    AdRow(
                        day=date.fromisoformat(r["date_start"]),
                        channel=self.channel,
                        campaign_id=str(r["campaign_id"]),
                        campaign=r["campaign_name"],
                        spend=dec(r.get("spend")),
                        impressions=int(r.get("impressions", 0)),
                        clicks=int(r.get("clicks", 0)),
                        conversions=self._action(r.get("actions")),
                        revenue=self._action(r.get("action_values")),
                    )
                )
            url = data.get("paging", {}).get("next")
        return rows


class MicrosoftAds:
    channel = "microsoft_ads"
    BASE = "https://reporting.api.bingads.microsoft.com/Reporting/v13/GenerateReport"

    def __init__(self, creds: Credentials, http: Http, sleep: object = None) -> None:
        self.creds, self.http = creds, http
        self.cfg = read("channels")["channels"]["microsoft_ads"]

    def fetch(self, start: date, end: date) -> list[AdRow]:
        headers = {"Authorization": f"Bearer {self.creds.token}", "DeveloperToken": self.creds.extra.get("developer_token", ""), "CustomerAccountId": self.creds.account_id}
        req = {
            "ReportRequest": {
                "Type": "CampaignPerformanceReportRequest",
                "Format": "Csv",
                "Aggregation": "Daily",
                "Columns": ["TimePeriod", "CampaignId", "CampaignName", "Impressions", "Clicks", "Spend", "Conversions", "Revenue"],
                "Scope": {"AccountIds": [self.creds.account_id]},
                "Time": {
                    "CustomDateRangeStart": {"Year": start.year, "Month": start.month, "Day": start.day},
                    "CustomDateRangeEnd": {"Year": end.year, "Month": end.month, "Day": end.day},
                },
            }
        }
        rid = self.http.request("POST", f"{self.BASE}/Submit", json=req, headers=headers).json()["ReportRequestId"]
        url = None
        for _ in range(int(self.cfg["max_polls"])):
            st = self.http.request("POST", f"{self.BASE}/Poll", json={"ReportRequestId": rid}, headers=headers).json()["ReportRequestStatus"]
            if st["Status"] == "Success":
                url = st["ReportDownloadUrl"]
                break
            if st["Status"] == "Error":
                raise ConnectorError(f"Microsoft Ads report {rid} failed")
            self.http.sleep(float(self.cfg["poll_interval_s"]))
        if url is None:
            # Success with no URL means the report has no rows
            return []
        blob = self.http.request("GET", url).content
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            text = zf.read(zf.namelist()[0]).decode("utf-8-sig")
        lines = text.splitlines()
        try:
            head = next(i for i, ln in enumerate(lines) if ln.startswith('"TimePeriod"'))
        except StopIteration as e:
            raise ConnectorError("Microsoft Ads report has no header row") from e
        body = [ln for ln in lines[head:] if ln.strip() and not ln.startswith('"©')]
        rows = []
        for r in csv.DictReader(body):
            rows.append(
                AdRow(
                    day=datetime.strptime(r["TimePeriod"], "%m/%d/%Y").date(),
                    channel=self.channel,
                    campaign_id=r["CampaignId"],
                    campaign=r["CampaignName"],
                    spend=dec(r["Spend"]),
                    impressions=int(dec(r["Impressions"])),
                    clicks=int(dec(r["Clicks"])),
                    conversions=dec(r["Conversions"]),
                    revenue=dec(r["Revenue"]),
                )
            )
        return rows


class TikTok:
    channel = "tiktok"
    URL = "https://business-api.tiktok.com/open_api/v1.3/report/integrated/get/"
    MAX_DAYS = 30  # stat_time_day requests may span at most 30 days

    def __init__(self, creds: Credentials, http: Http) -> None:
        self.creds, self.http = creds, http
        self.cfg = read("channels")["channels"]["tiktok"]

    def fetch(self, start: date, end: date) -> list[AdRow]:
        rows: list[AdRow] = []
        for s, e in _chunks(start, end, self.MAX_DAYS):
            page = 1
            while True:
                params = {
                    "advertiser_id": self.creds.account_id,
                    "report_type": "BASIC",
                    "data_level": "AUCTION_CAMPAIGN",
                    "dimensions": json.dumps(["campaign_id", "stat_time_day"]),
                    "metrics": json.dumps(["campaign_name", "spend", "impressions", "clicks", "conversion"]),
                    "start_date": s.isoformat(),
                    "end_date": e.isoformat(),
                    "page": str(page),
                    "page_size": str(self.cfg["page_size"]),
                }
                data = self.http.request("GET", self.URL, params=params, headers={"Access-Token": self.creds.token}).json()
                if data.get("code") != 0:
                    raise ConnectorError(f"TikTok code {data.get('code')}: {data.get('message')}")
                for r in data["data"]["list"]:
                    d, m = r["dimensions"], r["metrics"]
                    rows.append(
                        AdRow(
                            day=date.fromisoformat(d["stat_time_day"][:10]),
                            channel=self.channel,
                            campaign_id=str(d["campaign_id"]),
                            campaign=m["campaign_name"],
                            spend=dec(m["spend"]),
                            impressions=int(dec(m["impressions"])),
                            clicks=int(dec(m["clicks"])),
                            conversions=dec(m["conversion"]),
                            revenue=None,
                        )
                    )
                info = data["data"]["page_info"]
                if page >= int(info["total_page"]):
                    break
                page += 1
        return rows


class GA4:
    channel = "ga4"

    def __init__(self, creds: Credentials, http: Http) -> None:
        self.creds, self.http = creds, http
        self.cfg = read("channels")["ga4"]

    def fetch(self, start: date, end: date) -> list[Ga4Row]:
        url = f"https://analyticsdata.googleapis.com/v1beta/properties/{self.creds.account_id}:runReport"
        mapping: dict[str, str] = self.cfg["paid_source_medium"]
        rows: list[Ga4Row] = []
        offset = 0
        while True:
            body = {
                "dateRanges": [{"startDate": start.isoformat(), "endDate": end.isoformat()}],
                "dimensions": [{"name": "date"}, {"name": "sessionSourceMedium"}, {"name": "sessionCampaignName"}],
                "metrics": [{"name": self.cfg["key_event_metric"]}, {"name": self.cfg["revenue_metric"]}],
                "limit": self.cfg["page_size"],
                "offset": offset,
            }
            data = self.http.request("POST", url, json=body, headers={"Authorization": f"Bearer {self.creds.token}"}).json()
            names = [h["name"] for h in data.get("dimensionHeaders", [])]
            if names and names != ["date", "sessionSourceMedium", "sessionCampaignName"]:
                raise ConnectorError(f"GA4 returned unexpected dimensions {names}")
            for r in data.get("rows", []):
                dv = [v["value"] for v in r["dimensionValues"]]
                mv = [v["value"] for v in r["metricValues"]]
                sm = dv[1].strip().lower()
                rows.append(Ga4Row(day=datetime.strptime(dv[0], "%Y%m%d").date(), source_medium=sm, channel=mapping.get(sm), campaign=dv[2], conversions=dec(mv[0]), revenue=dec(mv[1])))
            offset += len(data.get("rows", []))
            if offset >= int(data.get("rowCount", 0)) or not data.get("rows"):
                return rows


KINDS = {"google_ads": GoogleAds, "meta": Meta, "microsoft_ads": MicrosoftAds, "tiktok": TikTok, "ga4": GA4}
