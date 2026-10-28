import pytest

from msd.analysis import service as analysis
from msd.proposals import engine
from msd.proposals.models import AuditEvent, Proposal
from msd.tenancy.scope import workspace_scope
from tests.conftest import make_workspace

pytestmark = pytest.mark.django_db


def test_tracking_loss_holds_the_budget_a_naive_rule_would_cut(agency, users):
    ws = make_workspace(agency, users, "kaffee", "meta-tag-broken")
    diag = analysis.run(ws.pk)
    props = engine.create(diag)
    assert [(p.kind, p.budget_change_per_day) for p in props] == [("tracking_loss", 0)]
    assert engine.naive_cuts(diag.result).get("meta", 0) > 0


def test_invalid_traffic_cuts_exactly_the_waste(workspace):
    diag = analysis.run(workspace.pk)
    p = next(p for p in engine.create(diag) if p.kind == "invalid_traffic")
    waste = next(c for c in diag.result["causes"] if c["type"] == "invalid_traffic")["evidence"]["excess_cost_eur"] / 7
    assert float(p.budget_change_per_day) == pytest.approx(-waste, abs=0.01)


def test_asking_twice_does_not_ask_the_manager_twice(workspace):
    a = engine.create(analysis.run(workspace.pk))
    b = engine.create(analysis.run(workspace.pk))
    assert [p.pk for p in a] == [p.pk for p in b]


def test_only_a_manager_decides_and_only_once(workspace, users):
    p = engine.create(analysis.run(workspace.pk))[0]
    with pytest.raises(engine.NotAllowed):
        engine.decide(p, users["analyst"], True, "", "analyst")
    engine.decide(p, users["manager"], True, "ok", "manager")
    with pytest.raises(engine.NotAllowed):
        engine.decide(p, users["manager"], False, "", "manager")
    with workspace_scope(workspace.pk):
        assert Proposal.objects.get(pk=p.pk).status == "approved"
        assert AuditEvent.objects.filter(action="proposal.approved").count() == 1
    assert engine.verify_chain(workspace.pk)[0]


def test_budget_guardrail():
    result = {
        "metric": "cpa",
        "periods": {"current": {"start": "2026-09-21", "end": "2026-09-27"}, "baseline": {"start": "2026-08-24", "end": "2026-09-20"}},
        "decomposition": {
            "units": {
                "a": {"current": {"spend": 700.0, "cpa": 30.0}, "baseline": {"spend": 2800.0, "cpa": 20.0}},
                "b": {"current": {"spend": 700.0, "cpa": 10.0}, "baseline": {"spend": 2800.0, "cpa": 10.0}},
            }
        },
        "causes": [{"type": "auction_pressure", "channel": "a", "campaign": None, "evidence": {}, "drivers": ["cpm"]}],
    }
    p = engine.plan(result)[0]
    assert p["budget_change_per_day"] == -15.0  # 15% of 100 a day; never more than the 30% cap
    assert p["rationale"]["to_channel"] == "b"
