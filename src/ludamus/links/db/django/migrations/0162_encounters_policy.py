import logging

from django.db import migrations, models

logger = logging.getLogger(__name__)


def fold_pages_into_policy(apps, schema_editor):
    del schema_editor
    # Two settings became one. `enabled_pages` decided whether the sphere had
    # an encounters page at all; `encounter_public_policy` decided who could
    # list an encounter publicly. The events feed is now the only page, and
    # `encounters_policy` decides who may create encounters for it.
    #
    # A sphere that had the page keeps encounters, open to everyone —
    # `disabled` had no successor, since "encounters, but none of them
    # listed" is not a state the new setting can hold. That widens who may
    # publish; the log records each sphere so it can be dialled back per
    # sphere from the panel.
    sphere_model = apps.get_model("db_main", "Sphere")
    for sphere in sphere_model.objects.iterator():
        if "encounters" not in sphere.enabled_pages:
            policy = "none"
        elif sphere.encounters_policy == "managers":
            policy = "managers"
        else:
            policy = "everyone"
        logger.info(
            "0162: sphere %s pages %r + policy %r -> %r",
            sphere.pk,
            sphere.enabled_pages,
            sphere.encounters_policy,
            policy,
        )
        sphere.encounters_policy = policy
        sphere.save(update_fields=["encounters_policy"])


class Migration(migrations.Migration):

    dependencies = [("db_main", "0161_space_programme_order")]

    operations = [
        migrations.RenameField(
            model_name="sphere",
            old_name="encounter_public_policy",
            new_name="encounters_policy",
        ),
        # Irreversible in substance: which spheres had which page enabled is
        # not recoverable once folded in. The schema changes reverse.
        migrations.RunPython(fold_pages_into_policy, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="sphere",
            name="encounters_policy",
            field=models.CharField(
                choices=[
                    ("none", "None"),
                    ("managers", "Managers"),
                    ("everyone", "Everyone"),
                ],
                default="none",
                max_length=20,
            ),
        ),
        migrations.RemoveField(model_name="sphere", name="enabled_pages"),
        migrations.RemoveField(model_name="sphere", name="default_page"),
    ]
