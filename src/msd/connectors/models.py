from __future__ import annotations

from django.db import models

from msd.tenancy.models import WorkspaceOwned


class Kind(models.TextChoices):
    GOOGLE_ADS = "google_ads", "Google Ads"
    META = "meta", "Meta"
    MICROSOFT_ADS = "microsoft_ads", "Microsoft Ads"
    TIKTOK = "tiktok", "TikTok"
    GA4 = "ga4", "Google Analytics 4"


class ConnectorAccount(WorkspaceOwned):
    kind = models.CharField(max_length=20, choices=Kind.choices)
    account_id = models.CharField(max_length=64)
    # live: credentials from the secret store; sim: a simulated account serving a scenario
    mode = models.CharField(max_length=8, choices=[("live", "Live"), ("sim", "Simulated")], default="sim")
    secret_ref = models.CharField(max_length=120, blank=True, help_text="Name of the secret holding the access token")
    scenario = models.CharField(max_length=120, blank=True)
    enabled = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["workspace", "kind"], name="one_account_per_kind")]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {self.account_id}"


class SyncRun(WorkspaceOwned):
    connector = models.ForeignKey(ConnectorAccount, on_delete=models.CASCADE, related_name="runs")
    status = models.CharField(max_length=10, choices=[("running", "Running"), ("ok", "OK"), ("failed", "Failed")], default="running")
    window_start = models.DateField()
    window_end = models.DateField()
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    rows = models.IntegerField(default=0)
    attempts = models.IntegerField(default=0)
    retries = models.IntegerField(default=0)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]
