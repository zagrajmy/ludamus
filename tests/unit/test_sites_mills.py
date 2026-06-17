from types import SimpleNamespace

from ludamus.mills.multiverse import SitesService


class _Spheres:
    def __init__(self, sites):
        self._sites = dict(sites)

    def read_site(self, sphere_id):
        return self._sites[sphere_id]


def test_read_site_returns_repo_site():
    site = SimpleNamespace(domain="ludamus.example.com", name="Root", pk=7)
    service = SitesService(_Spheres({1: site}))

    result = service.read_site(1)

    assert result is site
