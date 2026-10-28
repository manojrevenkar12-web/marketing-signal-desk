from django.db import migrations

from msd.tenancy.scope import enable_rls


class Migration(migrations.Migration):
    dependencies = [("metrics", "0001_initial")]

    operations = [
        enable_rls("metrics_addaily"),
        enable_rls("metrics_ga4daily"),
    ]
