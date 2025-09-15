from django.db import migrations


def fix_fk(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cur:
        # Find existing FK on subject_id referencing applications_subject
        cur.execute(
            """
            select tc.constraint_name
            from information_schema.table_constraints tc
            join information_schema.key_column_usage kcu on tc.constraint_name=kcu.constraint_name
            join information_schema.constraint_column_usage ccu on ccu.constraint_name=tc.constraint_name
            where tc.table_name='applications_application_subjects'
              and tc.constraint_type='FOREIGN KEY'
              and kcu.column_name='subject_id'
              and ccu.table_name='applications_subject'
            """
        )
        row = cur.fetchone()
        if row:
            (constraint_name,) = row
            cur.execute(
                f"ALTER TABLE public.applications_application_subjects DROP CONSTRAINT {constraint_name}"
            )
        # Check whether FK to subjects_subject already exists
        cur.execute(
            """
            select 1
            from information_schema.table_constraints tc
            join information_schema.key_column_usage kcu on tc.constraint_name=kcu.constraint_name
            join information_schema.constraint_column_usage ccu on ccu.constraint_name=tc.constraint_name
            where tc.table_name='applications_application_subjects'
              and tc.constraint_type='FOREIGN KEY'
              and kcu.column_name='subject_id'
              and ccu.table_name='subjects_subject'
            """
        )
        exists = cur.fetchone() is not None
        if not exists:
            cur.execute(
                """
                ALTER TABLE public.applications_application_subjects
                ADD CONSTRAINT applications_applica_subject_id_fk_subjects
                FOREIGN KEY (subject_id) REFERENCES public.subjects_subject (id)
                DEFERRABLE INITIALLY DEFERRED
                """
            )


def revert_fk(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cur:
        # Drop FK to subjects_subject if present
        cur.execute(
            """
            select tc.constraint_name
            from information_schema.table_constraints tc
            join information_schema.key_column_usage kcu on tc.constraint_name=kcu.constraint_name
            join information_schema.constraint_column_usage ccu on ccu.constraint_name=tc.constraint_name
            where tc.table_name='applications_application_subjects'
              and tc.constraint_type='FOREIGN KEY'
              and kcu.column_name='subject_id'
              and ccu.table_name='subjects_subject'
            """
        )
        row = cur.fetchone()
        if row:
            (constraint_name,) = row
            cur.execute(
                f"ALTER TABLE public.applications_application_subjects DROP CONSTRAINT {constraint_name}"
            )
        # Recreate FK to applications_subject if that table exists
        cur.execute(
            """
            select exists (
              select 1 from information_schema.tables
              where table_schema='public' and table_name='applications_subject'
            )
            """
        )
        (has_old_table,) = cur.fetchone()
        if has_old_table:
            cur.execute(
                """
                ALTER TABLE public.applications_application_subjects
                ADD CONSTRAINT applications_applica_subject_id_7e73f14d_fk_applicati
                FOREIGN KEY (subject_id) REFERENCES public.applications_subject (id)
                DEFERRABLE INITIALLY DEFERRED
                """
            )


class Migration(migrations.Migration):
    dependencies = [
        ("applications", "0004_alter_application_lesson_type"),
        ("subjects", "0001_initial"),
    ]

    operations = [migrations.RunPython(fix_fk, revert_fk)]

