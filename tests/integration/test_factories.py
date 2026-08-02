import pytest

from tests.integration.conftest import SphereFactory


@pytest.mark.django_db
def test_two_spheres_do_not_collide_on_an_identical_site_name():
    first = SphereFactory(site__name="Same Company")
    second = SphereFactory(site__name="Same Company")

    assert first.site_id != second.site_id
