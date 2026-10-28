"""Row-level security: the database itself keeps workspaces apart."""

import pytest
from django.db import IntegrityError, InternalError, ProgrammingError, connection, transaction

from msd.metrics.models import AdDaily
from msd.proposals.engine import audit, verify_chain
from msd.proposals.models import AuditEvent
from msd.tenancy.scope import current_workspace_id, workspace_scope
from tests.conftest import make_workspace

pytestmark = pytest.mark.django_db


def test_no_scope_sees_nothing(workspace):
    with workspace_scope(workspace.pk):
        assert AdDaily.objects.count() > 0
    assert AdDaily.objects.count() == 0  # even without a workspace filter


def test_one_workspace_never_sees_another(agency, users, workspace):
    other = make_workspace(agency, users, "other", "steady-state")
    with workspace_scope(other.pk):
        assert not AdDaily.objects.filter(workspace=workspace).exists()
        assert set(AdDaily.objects.values_list("workspace_id", flat=True)) == {other.pk}


def test_cannot_write_into_another_workspace(agency, users, workspace):
    other = make_workspace(agency, users, "other", None)
    with pytest.raises((ProgrammingError, IntegrityError, InternalError)), transaction.atomic(), workspace_scope(other.pk):
        row = AdDaily.objects.none().model(workspace_id=workspace.pk, day="2026-09-01", channel="meta", campaign_id="1", campaign="x", spend=1, impressions=1, clicks=1, conversions=1)
        row.save()


def test_scope_ends_with_its_block(workspace):
    with workspace_scope(workspace.pk):
        assert current_workspace_id() == workspace.pk
    assert current_workspace_id() is None


def test_audit_is_append_only_and_chained(workspace):
    with workspace_scope(workspace.pk):
        e = audit(workspace.pk, None, "test.one", "x", {"a": 1})
        audit(workspace.pk, None, "test.two", "x", {"a": 2})
    assert verify_chain(workspace.pk) == (True, 2)
    with pytest.raises((InternalError, ProgrammingError), match="append-only"), transaction.atomic(), workspace_scope(workspace.pk):
        AuditEvent.objects.filter(pk=e.pk).update(action="edited")
    with pytest.raises((InternalError, ProgrammingError), match="append-only"), transaction.atomic(), workspace_scope(workspace.pk):
        AuditEvent.objects.filter(pk=e.pk).delete()


def test_the_app_role_cannot_bypass_rls():
    with connection.cursor() as c:
        c.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        assert c.fetchone() == (False, False)
        c.execute("SELECT relforcerowsecurity FROM pg_class WHERE relname = 'metrics_addaily'")
        assert c.fetchone() == (True,)
