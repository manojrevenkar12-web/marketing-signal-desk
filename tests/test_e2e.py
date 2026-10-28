"""In a real browser, against a live server: the HTMX and Alpine flows, under the strict CSP."""

import os

import pytest

os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

PASSWORD = "a-long-test-password"


@pytest.fixture
def lumen(agency, users):
    from tests.conftest import make_workspace

    return make_workspace(agency, users, "lumen", "two-problems")


@pytest.fixture(autouse=True)
def _quiet_page(page):
    yield
    # let the live server finish every request before the database is flushed
    page.goto("about:blank")
    page.wait_for_timeout(200)


@pytest.fixture
def console(page):
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    return errors


def sign_in(page, live_server, name):
    page.goto(f"{live_server.url}/login/")
    page.fill("input[name=username]", name)
    page.fill("input[name=password]", PASSWORD)
    page.click("button:has-text('Sign in')")


def test_overview_ask_and_approve(page, live_server, lumen, console):
    sign_in(page, live_server, "manager")
    page.goto(f"{live_server.url}/w/lumen/")
    page.wait_for_selector("text=How CPA got from before to now")
    assert page.locator("svg rect.bridge-bar").count() >= 4
    page.click("a:has-text('Ask')")
    page.click("button:has-text('Why did our CPA go up last week?')")  # Alpine fills the box
    assert page.input_value("#question") == "Why did our CPA go up last week?"
    page.click("form button:has-text('Ask')")
    page.wait_for_selector("article mark.num-traced")
    assert page.locator("mark.num-untraced").count() == 0
    page.click("a:has-text('Open proposals')")
    card = page.locator("li[id^=proposal-]").first
    card.locator("input[name=note]").fill("looks right")
    card.locator("button:has-text('Approve')").click()
    page.wait_for_selector("text=Approved by")
    page.click("a:has-text('Audit trail')")
    page.wait_for_selector("text=Chain verified")
    assert console == []  # nothing blocked by the CSP, no script errors


def test_client_viewer_reads_but_cannot_act(page, live_server, lumen, console):
    sign_in(page, live_server, "client")
    page.goto(f"{live_server.url}/w/lumen/ask")
    assert page.locator("form textarea#question").count() == 0
    page.goto(f"{live_server.url}/w/lumen/proposals")
    assert page.locator("button:has-text('Approve')").count() == 0
    assert console == []


def test_workspace_switcher_theme_and_phone_width(page, live_server, lumen, console):
    page.set_viewport_size({"width": 390, "height": 844})
    sign_in(page, live_server, "analyst")
    page.goto(f"{live_server.url}/w/lumen/")
    page.wait_for_selector("text=What moved it")
    assert page.evaluate("document.documentElement.scrollWidth") <= 390
    page.click("button:has-text('Theme')")
    assert page.evaluate("document.documentElement.dataset.theme") == "light"
    page.click("button:has-text('Lumen')")
    page.wait_for_selector("[role=menu] a:has-text('Lumen')")
    assert console == []


def test_unknown_workspace_is_a_404(page, live_server, lumen):
    sign_in(page, live_server, "analyst")
    r = page.goto(f"{live_server.url}/w/someone-else/")
    assert r.status == 404
