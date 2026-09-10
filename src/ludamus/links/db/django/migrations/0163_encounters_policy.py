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
    # So the question each sphere is asked is "who could reach the create
    # form before?", which the two old settings answered together:
    #
    #   - The encounters page carried an unconditional create button, so
    #     every member could, whatever the publish policy said.
    #   - The timeline carried one too, but only for whoever the publish
    #     policy let publish — nobody, under `disabled`.
    #   - With neither page, there was no feed to create for.
    #
    # A sphere nobody could create in still keeps `managers` while rows
    # exist: every encounter route was reachable from the timeline, so `none`
    # would 404 share links that are live today.
    sphere_model = apps.get_model("db_main", "Sphere")
    for sphere in sphere_model.objects.iterator():
        pages = sphere.enabled_pages
        old_policy = sphere.encounters_policy
        if "encounters" in pages:
            policy = "everyone"
        elif "timeline" in pages and old_policy != "disabled":
            policy = old_policy
        elif sphere.encounters.exists():
            policy = "managers"
        else:
            policy = "none"
        logger.info(
            "0163: sphere %s pages %r + policy %r -> %r",
            sphere.pk,
            pages,
            old_policy,
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
