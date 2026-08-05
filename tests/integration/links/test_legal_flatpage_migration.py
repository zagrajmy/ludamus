from importlib import import_module

import pytest
from django.apps import apps
from django.conf import settings
from django.contrib.flatpages.models import FlatPage
from django.contrib.sites.models import Site

# The module name starts with a digit, so it can only be reached this way.
_migration = import_module(
    "ludamus.links.db.django.migrations.0141_drop_legal_flatpages"
)
drop_legal_flatpages = _migration.drop_legal_flatpages
restore_legal_flatpages = _migration.restore_legal_flatpages

URL = "/privacy-policy/"


def _flatpage(url: str, site: Site, *, title: str = "Privacy Policy") -> FlatPage:
    page = FlatPage.objects.create(url=url, title=title, content="<placeholder>")
    page.sites.add(site)
    return page


def _other_site(domain: str = "other.example.com") -> Site:
    return Site.objects.create(domain=domain, name=domain)


@pytest.mark.django_db
class TestDropLegalFlatpages:
    def test_removes_the_seeded_page(self):
        _flatpage(URL, Site.objects.get(pk=settings.SITE_ID))

        drop_legal_flatpages(apps, None)

        assert not FlatPage.objects.filter(url=URL).exists()

    def test_keeps_a_page_another_sphere_wrote(self):
        # Spheres are sites, FlatPage.url has no unique constraint, and a sphere
        # may have written its own policy through the admin. Deleting by url
        # alone would take it, and no reverse could bring the text back.
        _flatpage(URL, Site.objects.get(pk=settings.SITE_ID))
        _flatpage(URL, _other_site(), title="Polityka innej sfery")

        drop_legal_flatpages(apps, None)

        assert [page.title for page in FlatPage.objects.filter(url=URL)] == [
            "Polityka innej sfery"
        ]


@pytest.mark.django_db
class TestRestoreLegalFlatpages:
    def test_recreates_the_page_on_this_site(self):
        restore_legal_flatpages(apps, None)

        assert FlatPage.objects.filter(url=URL, sites__id=settings.SITE_ID).exists()

    def test_recreates_it_even_when_another_sphere_has_one(self):
        _flatpage(URL, _other_site(), title="Polityka innej sfery")

        restore_legal_flatpages(apps, None)

        assert FlatPage.objects.filter(url=URL, sites__id=settings.SITE_ID).exists()

    def test_survives_two_foreign_pages_at_the_same_url(self):
        _flatpage(URL, _other_site("a.example.com"))
        _flatpage(URL, _other_site("b.example.com"))

        restore_legal_flatpages(apps, None)

        assert FlatPage.objects.filter(url=URL, sites__id=settings.SITE_ID).exists()
