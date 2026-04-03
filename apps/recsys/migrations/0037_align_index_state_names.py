# Generated manually to align migration state with Django's current auto index names.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("recsys", "0036_tagmastery_and_more"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RenameIndex(
                    model_name="examblueprint",
                    old_name="recsys_examb_exam_vers_0a3a9e_idx",
                    new_name="recsys_exam_exam_ve_720af5_idx",
                ),
                migrations.RenameIndex(
                    model_name="examblueprintitem",
                    old_name="recsys_examb_bluepri_3c6497_idx",
                    new_name="recsys_exam_bluepri_fd61a1_idx",
                ),
                migrations.RenameIndex(
                    model_name="examversion",
                    old_name="recsys_exam_subject_name_idx",
                    new_name="recsys_exam_subject_12abc7_idx",
                ),
                migrations.RenameIndex(
                    model_name="examversion",
                    old_name="recsys_exam_slug_idx",
                    new_name="recsys_exam_slug_70e8d0_idx",
                ),
                migrations.RenameIndex(
                    model_name="examversion",
                    old_name="recsys_exam_status_idx",
                    new_name="recsys_exam_status_c17481_idx",
                ),
                migrations.RenameIndex(
                    model_name="task",
                    old_name="recsys_task_status_idx",
                    new_name="recsys_task_status_438d75_idx",
                ),
                migrations.RenameIndex(
                    model_name="variantpage",
                    old_name="recsys_var_sl_a2f963_idx",
                    new_name="recsys_vari_slug_feadc9_idx",
                ),
                migrations.RenameIndex(
                    model_name="varianttemplate",
                    old_name="recsys_varia_exam_ve_1b4795_idx",
                    new_name="recsys_vari_exam_ve_a77626_idx",
                ),
            ],
        ),
    ]
