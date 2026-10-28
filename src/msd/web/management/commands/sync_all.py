"""python manage.py sync_all: every enabled source of every workspace, its default window.
Run nightly (Cloud Scheduler -> Cloud Run job). A failing source is reported and skipped."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from msd.connectors.models import ConnectorAccount
from msd.connectors.sync import default_window, sync
from msd.tenancy.models import Workspace
from msd.tenancy.scope import workspace_scope


class Command(BaseCommand):
    help = "Sync every enabled source"

    def handle(self, *args: Any, **o: Any) -> None:
        failed = 0
        for ws in Workspace.objects.all():
            with workspace_scope(ws.pk):
                accts = list(ConnectorAccount.objects.filter(workspace=ws, enabled=True))
            for a in accts:
                run = sync(a, *default_window(a))
                failed += run.status != "ok"
                self.stdout.write(f"{ws.slug} {a.kind}: {run.status} {run.rows} rows {run.error[:120]}")
        if failed:
            self.stderr.write(f"{failed} source(s) failed")
