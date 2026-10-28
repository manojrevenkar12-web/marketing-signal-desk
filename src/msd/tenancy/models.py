"""Agencies run workspaces for their clients. Every row of client data carries its workspace, and
PostgreSQL row-level security makes a query see only the workspace set for the transaction
(msd.tenancy.scope). Django checks membership and role before that; the database is the backstop."""

from __future__ import annotations

from django.conf import settings
from django.db import models


class Agency(models.Model):
    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)

    def __str__(self) -> str:
        return self.name


class Workspace(models.Model):
    agency = models.ForeignKey(Agency, on_delete=models.PROTECT, related_name="workspaces")
    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    currency = models.CharField(max_length=3, default="EUR")
    target_cpa = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Role(models.TextChoices):
    ANALYST = "analyst", "Analyst"  # asks, investigates, drafts proposals
    MANAGER = "manager", "Manager"  # also approves or rejects budget proposals
    CLIENT = "client", "Client viewer"  # reads answers and decisions for their own workspace


class Membership(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=16, choices=Role.choices)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "workspace"], name="one_membership_per_workspace")]

    def __str__(self) -> str:
        return f"{self.user} in {self.workspace} as {self.role}"


class WorkspaceOwned(models.Model):
    """Base for every table holding a client's data. Its migration enables row-level security."""

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="+", db_index=True)

    class Meta:
        abstract = True
