"""The workspace a transaction may see, enforced by PostgreSQL row-level security.

Every client-data table has a policy `workspace_id = current_setting('msd.workspace_id')`. A
transaction that never sets it sees no rows and cannot write any. `workspace_scope` sets it with
`set_config(..., is_local => true)`, so it ends with the transaction and a pooled connection never
carries one request's workspace into the next."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from django.db import connection, transaction
from django.db.migrations.operations.base import Operation
from django.db.migrations.operations.special import RunSQL

SETTING = "msd.workspace_id"


def current_workspace_id() -> int | None:
    with connection.cursor() as c:
        c.execute("SELECT NULLIF(current_setting(%s, true), '')", [SETTING])
        v = c.fetchone()[0]
    return int(v) if v else None


@contextmanager
def workspace_scope(workspace_id: int) -> Iterator[None]:
    with transaction.atomic():
        prev = current_workspace_id()
        with connection.cursor() as c:
            c.execute("SELECT set_config(%s, %s, true)", [SETTING, str(int(workspace_id))])
        try:
            yield
        finally:
            if connection.connection is not None and not connection.needs_rollback:
                with connection.cursor() as c:
                    c.execute("SELECT set_config(%s, %s, true)", [SETTING, str(prev) if prev else ""])


def enable_rls(table: str) -> Operation:
    """Migration operation: row-level security on a workspace-owned table, applied even to the
    table's owner (FORCE), so the application role cannot bypass it."""
    cond = f"workspace_id = NULLIF(current_setting('{SETTING}', true), '')::bigint"
    return RunSQL(
        sql=[
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
            f"CREATE POLICY workspace_isolation ON {table} USING ({cond}) WITH CHECK ({cond})",
        ],
        reverse_sql=[f"DROP POLICY IF EXISTS workspace_isolation ON {table}", f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY", f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"],
    )
