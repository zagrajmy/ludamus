from django.apps import apps
from django.contrib.contenttypes.fields import GenericForeignKey


def test_no_installed_model_declares_a_generic_foreign_key():
    # settings.py neuters django-zeal's GenericForeignKey patch (it crashes on
    # Django 6.1), which silently drops N+1 detection for generic relations.
    # zeal patches globally, so this covers every installed app, not just ours.
    offenders = [
        f"{model._meta.label}.{field.name}"
        for model in apps.get_models()
        for field in model._meta.private_fields
        if isinstance(field, GenericForeignKey)
    ]

    assert offenders == []
