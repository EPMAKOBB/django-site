from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ("subjects", "0001_initial"),
        ("accounts", "0002_studentprofile_exam_versions"),
    ]

    operations = [
        migrations.CreateModel(
            name="StudyClass",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("description", models.TextField(blank=True)),
                ("join_code", models.CharField(blank=True, db_index=True, max_length=16, unique=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="classes_created", to=settings.AUTH_USER_MODEL),
                ),
            ],
            options={
                "ordering": ["-created_at", "name"],
            },
        ),
        migrations.AddIndex(
            model_name="studyclass",
            index=models.Index(fields=["join_code"], name="accounts_studyclass_join_code_idx"),
        ),
        migrations.CreateModel(
            name="ClassStudentMembership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("joined_at", models.DateTimeField(auto_now_add=True)),
                (
                    "student",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="class_memberships", to=settings.AUTH_USER_MODEL),
                ),
                (
                    "study_class",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="student_memberships", to="accounts.studyclass"),
                ),
            ],
            options={
                "unique_together": {("study_class", "student")},
            },
        ),
        migrations.AddIndex(
            model_name="classstudentmembership",
            index=models.Index(fields=["study_class", "student"], name="accounts_class_student_idx"),
        ),
        migrations.AddIndex(
            model_name="classstudentmembership",
            index=models.Index(fields=["student"], name="accounts_class_student_only_idx"),
        ),
        migrations.CreateModel(
            name="ClassTeacherSubject",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "study_class",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="teacher_subjects", to="accounts.studyclass"),
                ),
                (
                    "teacher",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="class_teachings", to=settings.AUTH_USER_MODEL),
                ),
                (
                    "subject",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="class_teachings", to="subjects.subject"),
                ),
            ],
            options={
                "unique_together": {("study_class", "teacher", "subject")},
            },
        ),
        migrations.AddIndex(
            model_name="classteachersubject",
            index=models.Index(fields=["study_class", "teacher", "subject"], name="accounts_class_teacher_subject_idx"),
        ),
        migrations.AddIndex(
            model_name="classteachersubject",
            index=models.Index(fields=["teacher", "subject"], name="accounts_teacher_subject_idx"),
        ),
        migrations.CreateModel(
            name="TeacherStudentLink",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("pending", "Pending"), ("active", "Active"), ("revoked", "Revoked")], default="pending", max_length=16)),
                ("invite_code", models.CharField(blank=True, db_index=True, max_length=20, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("activated_at", models.DateTimeField(blank=True, null=True)),
                (
                    "student",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="teacher_links", to=settings.AUTH_USER_MODEL),
                ),
                (
                    "subject",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="teacher_student_links", to="subjects.subject"),
                ),
                (
                    "teacher",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="student_links", to=settings.AUTH_USER_MODEL),
                ),
            ],
            options={
                "unique_together": {("teacher", "student", "subject")},
            },
        ),
        migrations.AddIndex(
            model_name="teacherstudentlink",
            index=models.Index(fields=["teacher", "student", "subject"], name="accounts_teacher_student_subject_idx"),
        ),
        migrations.AddIndex(
            model_name="teacherstudentlink",
            index=models.Index(fields=["invite_code"], name="accounts_teacher_student_code_idx"),
        ),
        migrations.CreateModel(
            name="TeacherSubjectInvite",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(db_index=True, max_length=20, unique=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "subject",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="subject_invites", to="subjects.subject"),
                ),
                (
                    "teacher",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="subject_invites", to=settings.AUTH_USER_MODEL),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="teachersubjectinvite",
            index=models.Index(fields=["teacher", "subject"], name="accounts_invite_teacher_subject_idx"),
        ),
        migrations.CreateModel(
            name="ClassInvite",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(db_index=True, max_length=16, unique=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "study_class",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="invites", to="accounts.studyclass"),
                ),
            ],
        ),
    ]

