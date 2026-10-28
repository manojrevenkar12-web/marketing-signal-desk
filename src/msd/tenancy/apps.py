from django.apps import AppConfig


class TenancyConfig(AppConfig):
    name = "msd.tenancy"
    label = "tenancy"
    default_auto_field = "django.db.models.BigAutoField"
