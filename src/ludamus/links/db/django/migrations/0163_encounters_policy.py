import logging

from django.db import migrations, models

logger = logging.getLogger(__name__)


def fold_pages_into_policy(apps, schema_editor):
    del schema_editor
    # Two settings became one. `enabled_pages` decided which pages the sphere
    # served; `encounter_public_policy` decided who could list an encounter
    # publicly. The events feed is now the only page, and `encounters_policy`
    # decides who may create encounters for it.
    #
    # Encounters were reachable from the encounters page *or* the timeline —
    # every encounter route was `reachable_via_timeline`, and the timeline
    # itself carried the create button. Reading `enabled_pages` alone would
    # 404 live share links on every timeline-only sphere, so both count.
    #
    # `disabled` maps to `everyone`: it never stopped anyone from creating an
    # encounter, only from listing one publicly, and "encounters, but none of
    # them listed" is not a state the new setting can hold. Preserving who may
    # create costs a wider publish surface; landing on `managers` instead
    # would take the feature away from everyone who had it. The log records
    # each sphere so it can be dialled back from the panel.
    sphere_model = apps.get_model("db_main", "Sphere")
    for sphere in sphere_model.objects.iterator():
        pages = sphere.enabled_pages
        if "encounters" not in pages and "timeline" not in pages:
            policy = "none"
        elif sphere.encounters_policy == "managers":
            policy = "managers"
        else:
            policy = "everyone"
        logger.info(
            "0163: sphere %s pages %r + policy %r -> %r",
            sphere.pk,
            sphere.enabled_pages,
            sphere.encounters_policy,
            policy,
        )
        sphere.encounters_policy = policy
        sphere.save(update_fields=["encounters_policy"])


class Migration(migrations.Migration):

    dependencies = [("db_main", "0162_rename_session_facilitator_name")]

    operations = [
        migrations.RenameField(
            model_name="sphere",
            old_name="encounter_public_policy",
            new_name="encounters_policy",
        ),
        # Irreversible: which spheres had which page enabled is not
        # recoverable once folded in, and reversing the schema alone leaves
        # rows holding "none", which the restored choices reject.
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
