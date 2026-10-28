from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("MSD_WRITER", "sim")
ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "scenarios" / "dev"


@pytest.fixture(autouse=True)
def _sim_writer():
    from msd.assistant import service
    from msd.assistant.writers import SimWriter

    service.set_writer(SimWriter(derived_number_rate=0.0))
    yield
    service.set_writer(None)


@pytest.fixture
def agency(db):
    from msd.tenancy.models import Agency

    return Agency.objects.create(name="Test agency", slug="test-agency")


@pytest.fixture
def users(db):
    from django.contrib.auth import get_user_model

    U = get_user_model()
    return {name: U.objects.create_user(name, password="a-long-test-password") for name in ("analyst", "manager", "client", "outsider")}


def make_workspace(agency, users, slug: str, scenario: str | None, sync_now: bool = True):
    from msd.connectors.models import ConnectorAccount
    from msd.connectors.sync import default_window, sync
    from msd.evals.run import ACCOUNTS
    from msd.tenancy.models import Membership, Workspace
    from msd.tenancy.scope import workspace_scope

    ws = Workspace.objects.create(agency=agency, name=slug.replace("-", " ").title(), slug=slug)
    for role in ("analyst", "manager", "client"):
        Membership.objects.create(user=users[role], workspace=ws, role=role)
    if scenario:
        with workspace_scope(ws.pk):
            accts = [ConnectorAccount.objects.create(workspace=ws, kind=k, account_id=a, mode="sim", scenario=f"scenarios/dev/{scenario}.yaml") for k, a in ACCOUNTS.items()]
        if sync_now:
            for a in accts:
                assert sync(a, *default_window(a)).status == "ok"
    return ws


@pytest.fixture
def workspace(agency, users):
    return make_workspace(agency, users, "lumen", "two-problems")


@pytest.fixture
def signed_in(client, users):
    def login(role: str):
        client.force_login(users[role])
        return client

    return login
