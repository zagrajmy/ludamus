# Generated manually for adding flatpages

from django.db import migrations


def create_flatpages(apps, schema_editor):
    FlatPage = apps.get_model("flatpages", "FlatPage")
    Site = apps.get_model("sites", "Site")

    # Get the default site
    try:
        default_site = Site.objects.get(pk=1)
    except Site.DoesNotExist:
        # If no default site exists, skip
        return

    # Create Privacy Policy page
    privacy_page, created = FlatPage.objects.get_or_create(
        url="/privacy-policy/",
        defaults={
            "title": "Privacy Policy",
            "content": "<placeholder>",
            "enable_comments": False,
            "registration_required": False,
        },
    )
    if created:
        privacy_page.sites.add(default_site)

    # Create Terms of Service page
    terms_page, created = FlatPage.objects.get_or_create(
        url="/terms-of-service/",
        defaults={
            "title": "Terms of Service",
            "content": "<placeholder>",
            "enable_comments": False,
            "registration_required": False,
        },
    )
    if created:
        terms_page.sites.add(default_site)


def remove_flatpages(apps, schema_editor):
    FlatPage = apps.get_model("flatpages", "FlatPage")
    FlatPage.objects.filter(url__in=["/privacy-policy/", "/terms-of-service/"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("db_main", "0007_alter_agendaitem_end_time_and_more"),
        ("flatpages", "0001_initial"),
        ("sites", "0001_initial"),
    ]

    operations = [migrations.RunPython(create_flatpages, remove_flatpages)]
