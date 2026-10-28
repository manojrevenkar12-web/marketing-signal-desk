from django.db import migrations

from msd.tenancy.scope import enable_rls


class Migration(migrations.Migration):
    dependencies = [("proposals", "0001_initial")]

    operations = [
        enable_rls("proposals_proposal"),
        enable_rls("proposals_auditevent"),
        migrations.RunSQL(
            sql=[
                """CREATE FUNCTION msd_audit_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
                   BEGIN RAISE EXCEPTION 'audit events are append-only'; END $$""",
                "CREATE TRIGGER audit_append_only BEFORE UPDATE OR DELETE ON proposals_auditevent FOR EACH ROW EXECUTE FUNCTION msd_audit_append_only()",
            ],
            reverse_sql=["DROP TRIGGER IF EXISTS audit_append_only ON proposals_auditevent", "DROP FUNCTION IF EXISTS msd_audit_append_only()"],
        ),
    ]
