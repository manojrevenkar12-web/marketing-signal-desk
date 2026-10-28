"""Normalised daily rows. Money is Decimal; platform numbers are stored as each platform reports
them, and GA4 next to them, so the analysis can compare the two."""

from __future__ import annotations

from django.db import models

from msd.tenancy.models import WorkspaceOwned


class AdDaily(WorkspaceOwned):
    day = models.DateField()
    channel = models.CharField(max_length=20)
    campaign_id = models.CharField(max_length=64)
    campaign = models.CharField(max_length=255)
    spend = models.DecimalField(max_digits=14, decimal_places=2)
    impressions = models.BigIntegerField()
    clicks = models.BigIntegerField()
    conversions = models.DecimalField(max_digits=14, decimal_places=2)
    revenue = models.DecimalField(max_digits=14, decimal_places=2, null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["workspace", "day", "channel", "campaign_id"], name="one_ad_row")]
        indexes = [models.Index(fields=["workspace", "channel", "day"])]


class Ga4Daily(WorkspaceOwned):
    day = models.DateField()
    source_medium = models.CharField(max_length=255)
    channel = models.CharField(max_length=20, null=True)  # noqa: DJ001  # null = not paid media (organic, direct, email); filtered with isnull
    campaign = models.CharField(max_length=255)
    conversions = models.DecimalField(max_digits=14, decimal_places=2)
    revenue = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["workspace", "day", "source_medium", "campaign"], name="one_ga4_row")]
        indexes = [models.Index(fields=["workspace", "day"])]
