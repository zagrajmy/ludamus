import logging

from django.db import migrations, models

logger = logging.getLogger(__name__)


def policy_for(pages, old_policy, *, has_encounters):
    """Pick the sphere's new policy from the two settings it replaces.

    Two settings became one. `enabled_pages` decided which pages the sphere
    served; `encounter_public_policy` decided who could list an encounter
    publicly. The events feed is now the only page, and `encounters_policy`
    decides who may create encounters for it.

    So the question each sphere is asked is "who could reach the create form
    before?", which the two old settings answered together:

      - The encounters page carried an unconditional create button, so every
        member could, whatever the publish policy said.
      - The timeline carried one too, but only for whoever the publish policy
        let publish — nobody, under `disabled`, though the form itself stayed
        reachable by URL.
      - With neither page, every encounter route 404'd.

    Returns:
        A timeline-only sphere under `disabled` offered the form to nobody,
        but its encounter routes were all reachable, so `none` would 404
        share links that are live today: it keeps `managers` while rows
        exist.
    """
    if "encounters" in pages:
        return "everyone"
    if "timeline" not in pages:
        return "none"
    if old_policy != "disabled":
        return old_policy
    return "managers" if has_encounters else "none"


def fold_pages_into_policy(apps, schema_editor):
    del schema_editor
    sphere_model = apps.get_model("db_main", "Sphere")
    for sphere in sphere_model.objects.iterator():
        pages = sphere.enabled_pages
        old_policy = sphere.encounters_policy
        policy = policy_for(
            pages, old_policy, has_encounters=sphere.encounters.exists()
        )
        logger.info(
            "0163: sphere %s pages %r + policy %r -> %r",
            sphere.pk,
            pages,
            old_policy,
            policy,
        )
        sphere.encounters_policy = policy
        sphere.save(update_fields=["encounters_policy"])


def unfold_policy_into_pages(apps, schema_editor):
    del schema_editor
    sphere_model = apps.get_model("db_main", "Sphere")
    sphere_model.objects.filter(encounters_policy="none").update(
        encounters_policy="disabled"
    )


class Migration(migrations.Migration):

    dependencies = [("db_main", "0162_rename_session_facilitator_name")]

    operations = [
        migrations.RenameField(
            model_name="sphere",
            old_name="encounter_public_policy",
            new_name="encounters_policy",
        ),
        # Which page each sphere had enabled is not recoverable, so the
        # reverse only has to put the column back in the old vocabulary:
        # "none" has no pre-image but `disabled`, and a SphereDTO read of
        # anything else raises on every page that names the sphere.
        migrations.RunPython(fold_pages_into_policy, unfold_policy_into_pages),
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
