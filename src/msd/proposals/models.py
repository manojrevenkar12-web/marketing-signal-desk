from __future__ import annotations

from django.conf import settings
from django.db import models

from msd.tenancy.models import WorkspaceOwned


class Proposal(WorkspaceOwned):
    class Status(models.TextChoices):
        PROPOSED = "proposed", "Proposed"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    diagnosis = models.ForeignKey("analysis.Diagnosis", on_delete=models.CASCADE, related_name="proposals")
    kind = models.CharField(max_length=40)
    channel = models.CharField(max_length=20, blank=True)
    campaign = models.CharField(max_length=255, blank=True)
    title = models.CharField(max_length=200)
    action = models.TextField()
    budget_change_per_day = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    rationale = models.JSONField(default=dict)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PROPOSED)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["created_at"]


class AuditEvent(WorkspaceOwned):
    """Append-only (a trigger refuses UPDATE and DELETE) and hash-chained per workspace."""

    at = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    action = models.CharField(max_length=60)
    subject = models.CharField(max_length=120)
    data = models.JSONField(default=dict)
    prev_hash = models.CharField(max_length=64)
    hash = models.CharField(max_length=64)

    class Meta:
        ordering = ["id"]
