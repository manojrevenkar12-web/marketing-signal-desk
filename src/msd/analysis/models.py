from __future__ import annotations

from django.db import models

from msd.tenancy.models import WorkspaceOwned


class Diagnosis(WorkspaceOwned):
    created_at = models.DateTimeField(auto_now_add=True)
    metric = models.CharField(max_length=8, default="cpa")
    source = models.CharField(max_length=10, default="ga4")
    baseline_start = models.DateField()
    baseline_end = models.DateField()
    current_start = models.DateField()
    current_end = models.DateField()
    material = models.BooleanField(default=False)
    result = models.JSONField()

    class Meta:
        ordering = ["-created_at"]
