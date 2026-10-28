from django.db import migrations

from msd.tenancy.scope import enable_rls


class Migration(migrations.Migration):
    dependencies = [("connectors", "0001_initial")]

    operations = [
        enable_rls("connectors_connectoraccount"),
        enable_rls("connectors_syncrun"),
    ]
