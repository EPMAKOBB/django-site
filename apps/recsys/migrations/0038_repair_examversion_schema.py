from django.db import migrations


def repair_examversion_schema(apps, schema_editor):
    connection = schema_editor.connection
    table_name = "recsys_examversion"

    existing_tables = set(connection.introspection.table_names())
    if table_name not in existing_tables:
        return

    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(cursor, table_name)
        existing_columns = {column.name for column in description}

        if "slug" not in existing_columns:
            schema_editor.execute(
                "ALTER TABLE recsys_examversion "
                "ADD COLUMN slug varchar(128) NULL"
            )

        if "status" not in existing_columns:
            schema_editor.execute(
                "ALTER TABLE recsys_examversion "
                "ADD COLUMN status varchar(32) NULL"
            )

        constraints = connection.introspection.get_constraints(cursor, table_name)
        existing_indexes = set(constraints.keys())

        if "recsys_exam_slug_70e8d0_idx" not in existing_indexes:
            schema_editor.execute(
                "CREATE INDEX recsys_exam_slug_70e8d0_idx "
                "ON recsys_examversion (slug)"
            )

        if "recsys_exam_status_c17481_idx" not in existing_indexes:
            schema_editor.execute(
                "CREATE INDEX recsys_exam_status_c17481_idx "
                "ON recsys_examversion (status)"
            )


class Migration(migrations.Migration):

    dependencies = [
        ("recsys", "0037_align_index_state_names"),
    ]

    operations = [
        migrations.RunPython(repair_examversion_schema, migrations.RunPython.noop),
    ]
