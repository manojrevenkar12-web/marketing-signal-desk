from django.db import migrations

from msd.tenancy.scope import enable_rls


class Migration(migrations.Migration):
    dependencies = [("assistant", "0001_initial")]

    operations = [
        enable_rls("assistant_question"),
    ]
