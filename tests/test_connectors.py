from decimal import Decimal

import httpx
import pytest

from msd.connectors.base import ConnectorError, Credentials, Http, dec
from msd.connectors.platforms import GA4, KINDS, Meta, TikTok
from msd.sim.fake_apis import TOKEN, FakeApis, Faults
from msd.sim.world import build, load_scenario
from tests.conftest import DEV

WORLD = build(load_scenario(DEV / "bing-export-gap.yaml"))
S, E = WORLD.scenario.start, WORLD.scenario.end
CREDS = Credentials(TOKEN, "1234567890", {"developer_token": "x"})


def http(faults=None):
    return Http(FakeApis(WORLD, faults or Faults()).transport(), sleep=lambda s: None)


@pytest.mark.parametrize("kind", ["google_ads", "meta", "microsoft_ads", "tiktok"])
def test_platforms_reconcile_to_the_cent_through_429_and_503(kind):
    h = http()
    rows = KINDS[kind](CREDS, h).fetch(S, E)
    missing = WORLD.missing(kind)
    truth = [r for r in WORLD.rows if r.channel == kind and r.day not in missing]
    assert len(rows) == len(truth)
    assert sum(r.spend for r in rows) == Decimal(str(round(sum(r.spend for r in truth), 2)))
    assert h.retries >= 2  # one 429, one 503


def test_meta_counts_each_purchase_once():
    rows = Meta(CREDS, http(Faults(False, False))).fetch(S, E)
    want = sum(r.platform_conversions for r in WORLD.rows if r.channel == "meta")
    assert float(sum(r.conversions for r in rows)) == pytest.approx(want, abs=0.5)  # not three times


def test_tiktok_splits_long_windows():
    rows = TikTok(CREDS, http(Faults(False, False))).fetch(S, E)  # 56 days: the API allows 30
    assert len({r.day for r in rows}) == (E - S).days + 1


def test_ga4_keeps_organic_apart():
    rows = GA4(CREDS, http(Faults(False, False))).fetch(S, E)
    paid = [r for r in rows if r.channel]
    assert {r.channel for r in paid} == {"google_ads", "meta", "microsoft_ads", "tiktok"}
    assert any(r.channel is None and "organic" in r.source_medium for r in rows)
    assert float(sum(r.conversions for r in paid)) == sum(r.ga4_conversions for r in WORLD.rows)


def test_bad_credentials_fail_fast_without_retrying():
    h = http(Faults(False, False))
    with pytest.raises(ConnectorError, match="401"):
        KINDS["google_ads"](Credentials("wrong", "1", {"developer_token": "x"}), h).fetch(S, E)
    assert h.retries == 0


def test_gives_up_after_max_retries():
    h = Http(httpx.MockTransport(lambda r: httpx.Response(503)), sleep=lambda s: None)
    with pytest.raises(ConnectorError, match="503"):
        h.request("GET", "https://example.invalid/x")
    assert h.attempts == h.max_retries + 1


def test_money_never_goes_through_float():
    assert dec("1,234.10") == Decimal("1234.10") and dec(None) == 0 and dec("") == 0
