"""What every connector shares: the normalised row shapes, credentials, and an HTTP client that
retries what is worth retrying (429 with Retry-After, 5xx, dropped connections) and nothing else."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Protocol

import httpx

from msd.conf import read


class ConnectorError(Exception):
    """The source refused or broke in a way retrying will not fix (auth, bad request, schema)."""


@dataclass(frozen=True)
class AdRow:
    day: date
    channel: str
    campaign_id: str
    campaign: str
    spend: Decimal
    impressions: int
    clicks: int
    conversions: Decimal  # as the platform reports them
    revenue: Decimal | None  # None when the platform does not report value


@dataclass(frozen=True)
class Ga4Row:
    day: date
    source_medium: str
    channel: str | None  # the paid channel this traffic maps to, None for organic, direct...
    campaign: str
    conversions: Decimal
    revenue: Decimal


@dataclass(frozen=True)
class Credentials:
    token: str
    account_id: str
    extra: dict[str, str]


class Connector(Protocol):
    channel: str

    def fetch(self, start: date, end: date) -> list[AdRow] | list[Ga4Row]: ...


class Http:
    def __init__(self, transport: httpx.BaseTransport | None = None, sleep: Any = time.sleep) -> None:
        cfg = read("channels")["http"]
        self.client = httpx.Client(transport=transport, timeout=cfg["timeout_s"])
        self.max_retries = int(cfg["max_retries"])
        self.backoff = float(cfg["backoff_base_s"])
        self.sleep = sleep
        self.attempts = 0
        self.retries = 0

    def request(self, method: str, url: str, **kw: Any) -> httpx.Response:
        for attempt in range(self.max_retries + 1):
            self.attempts += 1
            try:
                r = self.client.request(method, url, **kw)
            except httpx.TransportError as e:
                if attempt == self.max_retries:
                    raise ConnectorError(f"{method} {url}: {e}") from e
                self.retries += 1
                self.sleep(self.backoff * 2**attempt)
                continue
            if r.status_code == 429 or r.status_code >= 500:
                if attempt == self.max_retries:
                    raise ConnectorError(f"{method} {httpx.URL(url).host}: HTTP {r.status_code} after {attempt + 1} attempts")
                self.retries += 1
                wait = r.headers.get("Retry-After")
                self.sleep(float(wait) if wait and wait.replace(".", "", 1).isdigit() else self.backoff * 2**attempt)
                continue
            if r.status_code >= 400:
                raise ConnectorError(f"{method} {httpx.URL(url).host}: HTTP {r.status_code}: {r.text[:300]}")
            return r
        raise ConnectorError("unreachable")


def dec(v: Any) -> Decimal:
    """Platform numbers arrive as strings ("1,234", "12.50") or floats; never parse money as float."""
    if v is None or v == "":
        return Decimal(0)
    return Decimal(str(v).replace(",", ""))
