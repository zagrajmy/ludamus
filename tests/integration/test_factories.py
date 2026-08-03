from tests.integration.conftest import SphereFactory


# The original break: SiteFactory derived its domain from a non-unique
# Faker("company") and got-or-created on it, so two spheres whose sites drew the
# same name collapsed onto one Site row.
def test_spheres_built_from_one_site_name_do_not_share_a_site():
    first = SphereFactory(site__name="Same Company")
    second = SphereFactory(site__name="Same Company")

    assert first.site_id != second.site_id
