from __future__ import annotations

from django.conf import settings
from django.db import models

from msd.tenancy.models import WorkspaceOwned


class Question(WorkspaceOwned):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        ANSWERED = "answered", "Answered"
        FAILED = "failed", "Failed"

    asked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    text = models.CharField(max_length=500)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    created_at = models.DateTimeField(auto_now_add=True)
    plan = models.JSONField(null=True, blank=True)
    diagnosis = models.ForeignKey("analysis.Diagnosis", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    answer = models.TextField(blank=True)
    numbers = models.JSONField(default=list, blank=True)  # every number in the answer and where it came from
    model = models.CharField(max_length=120, blank=True)
    corrections = models.IntegerField(default=0)
    fallback = models.BooleanField(default=False)  # the written answer came from the template, not the model
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
