"""python manage.py seed_demo: a fictional agency with three client workspaces, each fed by
simulated ad accounts playing a scenario, and three demo users. Safe to run twice."""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from msd.connectors.models import ConnectorAccount
from msd.connectors.sync import default_window, sync
from msd.tenancy.models import Agency, Membership, Workspace
from msd.tenancy.scope import workspace_scope

PASSWORD = "signal-desk-demo"
WORKSPACES = [
    ("lumen-skincare", "Lumen Skincare", "scenarios/dev/two-problems.yaml"),
    ("northwind-outdoor", "Northwind Outdoor", "scenarios/dev/tiktok-push.yaml"),
    ("kaffeehaus-berg", "Kaffeehaus Berg", "scenarios/dev/meta-tag-broken.yaml"),
]
ACCOUNTS = {"google_ads": "1234567890", "meta": "1029384756", "microsoft_ads": "180012345", "tiktok": "7012345678901234567", "ga4": "312345678"}


class Command(BaseCommand):
    help = "Create the demo agency, workspaces, users and data"

    def handle(self, *args: Any, **o: Any) -> None:
        User = get_user_model()
        agency, _ = Agency.objects.get_or_create(slug="brightline", defaults={"name": "Brightline Digital"})
        users = {}
        for username, first, last in (("anna", "Anna", "Weber"), ("max", "Max", "Brandt"), ("lumen-client", "Lena", "Koch")):
            u, created = User.objects.get_or_create(username=username, defaults={"first_name": first, "last_name": last})
            if created:
                u.set_password(PASSWORD)
                u.save()
            users[username] = u
        for slug, name, scenario in WORKSPACES:
            ws, _ = Workspace.objects.get_or_create(slug=slug, defaults={"name": name, "agency": agency})
            Membership.objects.get_or_create(user=users["anna"], workspace=ws, defaults={"role": "analyst"})
            Membership.objects.get_or_create(user=users["max"], workspace=ws, defaults={"role": "manager"})
            if slug == "lumen-skincare":
                Membership.objects.get_or_create(user=users["lumen-client"], workspace=ws, defaults={"role": "client"})
            with workspace_scope(ws.pk):
                accts = [ConnectorAccount.objects.get_or_create(workspace=ws, kind=k, defaults={"account_id": a, "mode": "sim", "scenario": scenario})[0] for k, a in ACCOUNTS.items()]
            for a in accts:
                run = sync(a, *default_window(a))
                self.stdout.write(f"{name}: {a.get_kind_display()} {run.status}, {run.rows} rows, {run.retries} retries")
        self.stdout.write(f"Users anna (analyst), max (manager), lumen-client (client viewer); password {PASSWORD}")
