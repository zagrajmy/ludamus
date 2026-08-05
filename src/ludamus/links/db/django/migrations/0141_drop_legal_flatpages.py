from django.conf import settings
from django.db import migrations

URLS = ["/privacy-policy/", "/terms-of-service/"]
TITLES = ["Privacy Policy", "Terms of Service"]


def drop_legal_flatpages(apps, schema_editor):
    # Scoped to the default site, which is the only one 0008 seeded. FlatPage.url
    # carries no unique constraint and flatpages resolve per site, so a bare
    # url__in filter would also delete a policy a sphere wrote for itself
    # through the admin — rows this migration never created and cannot restore.
    FlatPage = apps.get_model("flatpages", "FlatPage")
    FlatPage.objects.filter(url__in=URLS, sites__id=settings.SITE_ID).delete()


def restore_legal_flatpages(apps, schema_editor):
    # Restores the rows, not the text: both documents live in
    # src/ludamus/content/legal now, and 0008 seeded a placeholder anyway.
    # Rolling back means serving them from the database again, which means
    # pasting the content back in by hand, exactly as before.
    FlatPage = apps.get_model("flatpages", "FlatPage")
    Site = apps.get_model("sites", "Site")
    default_site = Site.objects.filter(pk=settings.SITE_ID).first()
    if default_site is None:
        return

    for url, title in zip(URLS, TITLES, strict=True):
        page, created = FlatPage.objects.get_or_create(
            url=url,
            defaults={
                "title": title,
                "content": "<placeholder>",
                "enable_comments": False,
                "registration_required": False,
            },
        )
        if created:
            page.sites.add(default_site)


class Migration(migrations.Migration):

    dependencies = [
        ("db_main", "0140_alter_event_auto_confirm_sessions"),
        ("flatpages", "0001_initial"),
        ("sites", "0001_initial"),
    ]

    operations = [migrations.RunPython(drop_legal_flatpages, restore_legal_flatpages)]
