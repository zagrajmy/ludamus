from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("db_main", "0080_event_allow_facilitator_session_edit_and_more"),
        ("db_main", "0082_eventintegration_import_failures_json"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="eventintegration", name="import_failures_json"
        ),
        migrations.CreateModel(
            name="ImportLogEntry",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("row_index", models.IntegerField()),
                (
                    "status",
                    models.CharField(
                        choices=[("success", "success"), ("skipped", "skipped")],
                        max_length=16,
                    ),
                ),
                ("reason", models.TextField(blank=True, default="")),
                ("response_json", models.TextField(default="{}")),
                ("title", models.CharField(blank=True, default="", max_length=255)),
                (
                    "display_name",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                ("attempted_at", models.DateTimeField(auto_now_add=True)),
                (
                    "integration",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="log_entries",
                        to="db_main.eventintegration",
                    ),
                ),
                (
                    "session",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="import_log_entries",
                        to="db_main.session",
                    ),
                ),
            ],
            options={
                "db_table": "import_log_entry",
                "ordering": ("-attempted_at", "-pk"),
                "indexes": [
                    models.Index(
                        fields=["integration", "status", "-attempted_at"],
                        name="ile_int_status_at_idx",
                    ),
                    models.Index(
                        fields=["integration", "row_index"], name="ile_int_row_idx"
                    ),
                    models.Index(fields=["session"], name="ile_session_idx"),
                ],
            },
        ),
    ]
