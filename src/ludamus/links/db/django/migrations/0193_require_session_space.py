import django.db.models.deletion
from django.db import migrations, models


def unschedule_spaceless_items(apps, schema_editor):
    # NOTE: going back, a space is required again, so an item placed without
    # one cannot stay; its session returns to being an unscheduled proposal.
    items = apps.get_model("db_main", "AgendaItem").objects.using(
        schema_editor.connection.alias
    )
    items.filter(space__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [("db_main", "0192_remove_encounterrsvp_ip_address")]

    operations = [
        migrations.AddField(
            model_name="event",
            name="require_session_space",
            field=models.BooleanField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name="sphere",
            name="require_session_space",
            field=models.BooleanField(default=True),
        ),
        migrations.AlterField(
            model_name="agendaitem",
            name="space",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="agenda_items",
                to="db_main.space",
            ),
        ),
        migrations.RunPython(migrations.RunPython.noop, unschedule_spaceless_items),
    ]
