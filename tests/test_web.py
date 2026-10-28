import pytest

from msd.proposals.models import Proposal
from msd.tenancy.scope import workspace_scope

pytestmark = pytest.mark.django_db


def test_sign_in_required(client, workspace):
    assert client.get("/w/lumen/").status_code == 302


def test_outsiders_get_404_not_403(signed_in, workspace):
    assert signed_in("outsider").get("/w/lumen/").status_code == 404


def test_csp_has_no_inline_or_eval(signed_in, workspace):
    r = signed_in("analyst").get("/w/lumen/")
    csp = r.headers["Content-Security-Policy"]
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp and "nonce-" in csp


def test_overview_loads_the_diagnosis_lazily(signed_in, workspace):
    c = signed_in("analyst")
    page = c.get("/w/lumen/").content.decode()
    assert 'hx-trigger="load"' in page and "Reading the week" in page
    frag = c.get("/w/lumen/overview/diagnosis", headers={"HX-Request": "true"}).content.decode()
    assert "How CPA got from before to now" in frag and "<html" not in frag
    assert "Spark Ads - Creators on TikTok" in frag


def test_empty_state_without_data(signed_in, agency, users):
    from tests.conftest import make_workspace

    make_workspace(agency, users, "empty", None)
    assert "No data yet" in signed_in("analyst").get("/w/empty/").content.decode()


def test_ask_returns_the_answer_fragment(signed_in, workspace):
    r = signed_in("analyst").post("/w/lumen/ask", {"question": "Why did our CPA go up last week?"}, headers={"HX-Request": "true"})
    html = r.content.decode()
    assert r.status_code == 200 and "num-traced" in html and "num-untraced" not in html
    assert "Proposed, waiting for a manager" in html


def test_client_viewers_cannot_ask_or_decide(signed_in, workspace):
    c = signed_in("client")
    assert c.post("/w/lumen/ask", {"question": "Why did CPA go up?"}).status_code == 403
    signed_in("analyst").post("/w/lumen/ask", {"question": "Why did our CPA go up last week?"})
    with workspace_scope(workspace.pk):
        p = Proposal.objects.first()
    c = signed_in("client")
    assert c.post(f"/w/lumen/proposals/{p.pk}/decide", {"decision": "approve"}).status_code == 403
    assert "Approve" not in c.get("/w/lumen/proposals").content.decode()


def test_manager_approves_and_the_audit_shows_it(signed_in, workspace):
    signed_in("analyst").post("/w/lumen/ask", {"question": "Why did our CPA go up last week?"})
    with workspace_scope(workspace.pk):
        p = Proposal.objects.first()
    m = signed_in("manager")
    r = m.post(f"/w/lumen/proposals/{p.pk}/decide", {"decision": "approve", "note": "go"}, headers={"HX-Request": "true"})
    assert r.status_code == 200 and "Approved by" in r.content.decode()
    assert m.post(f"/w/lumen/proposals/{p.pk}/decide", {"decision": "reject"}).status_code == 409
    audit = m.get("/w/lumen/audit").content.decode()
    assert "proposal.approved" in audit and "Chain verified" in audit


def test_empty_question_is_explained(signed_in, workspace):
    r = signed_in("analyst").post("/w/lumen/ask", {"question": "  "}, headers={"HX-Request": "true"})
    assert r.status_code == 422 and "Write a question first" in r.content.decode()


def test_failed_question_offers_a_retry(signed_in, workspace, monkeypatch):
    from msd.analysis import service as analysis

    def boom(*a, **k):
        raise RuntimeError("database went away")

    monkeypatch.setattr(analysis, "run", boom)
    html = signed_in("analyst").post("/w/lumen/ask", {"question": "Why did our CPA go up last week?"}, headers={"HX-Request": "true"}).content.decode()
    assert "could not be answered" in html and "Try again" in html


def test_sync_now_and_checks(signed_in, workspace):
    from msd.connectors.models import ConnectorAccount

    with workspace_scope(workspace.pk):
        a = ConnectorAccount.objects.get(workspace=workspace, kind="meta")
    c = signed_in("analyst")
    r = c.post(f"/w/lumen/connections/{a.pk}/sync", headers={"HX-Request": "true"})
    assert r.status_code == 200 and "OK" in r.content.decode()
    c.get("/w/lumen/overview/diagnosis")
    assert "Invalid traffic" in c.get("/w/lumen/checks").content.decode()


def test_health(client, db):
    assert client.get("/healthz").json() == {"status": "ok"}
