from django.db import migrations

URLS = ["/privacy-policy/", "/terms-of-service/"]


def drop_legal_flatpages(apps, schema_editor):
    FlatPage = apps.get_model("flatpages", "FlatPage")
    FlatPage.objects.filter(url__in=URLS).delete()


def restore_legal_flatpages(apps, schema_editor):
    # Reverses the row, not the text: the documents live in
    # src/ludamus/content/legal now, and 0008 seeded these with a placeholder
    # anyway. Anyone rolling back wants the pages served from the database
    # again, which means pasting the content in by hand, as before.
    FlatPage = apps.get_model("flatpages", "FlatPage")
    Site = apps.get_model("sites", "Site")
    default_site = Site.objects.filter(pk=1).first()
    if default_site is None:
        return

    for url, title in zip(URLS, ["Privacy Policy", "Terms of Service"], strict=True):
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
