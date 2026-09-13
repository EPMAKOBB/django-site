import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0007_student_records"),
    ]

    operations = [
        # This is deliberately a separate transaction from the data backfill
        # in 0007. PostgreSQL must commit deferred FK trigger events before it
        # can alter the affected relationship and its indexes.
        migrations.AlterField(
            model_name="teacherstudentlink",
            name="student_record",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="teacher_links",
                to="students.studentrecord",
            ),
        ),
        migrations.AlterUniqueTogether(
            name="teacherstudentlink",
            unique_together={("teacher", "student_record", "subject")},
        ),
        migrations.RemoveIndex(
            model_name="teacherstudentlink",
            name="accounts_te_teacher_f4cd51_idx",
        ),
        migrations.RemoveIndex(
            model_name="teacherstudentlink",
            name="accounts_te_invite__38c52a_idx",
        ),
        migrations.AddIndex(
            model_name="teacherstudentlink",
            index=models.Index(
                fields=["teacher", "student_record", "subject"],
                name="accounts_tsr_subject_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="teacherstudentlink",
            index=models.Index(
                fields=["invite_code"],
                name="acct_tsl_invite_code_idx",
            ),
        ),
    ]
