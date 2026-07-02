from types import SimpleNamespace

from ludamus.mills.multiverse import SitesService


class _Spheres:
    def __init__(self, sites):
        self._sites = dict(sites)

    def read_site(self, sphere_id):
        return self._sites[sphere_id]


class _Directory:
    def __init__(self, spheres):
        self._spheres = list(spheres)

    def list_all(self):
        return list(self._spheres)


def test_read_site_returns_repo_site():
    site = SimpleNamespace(domain="ludamus.example.com", name="Root", pk=7)
    service = SitesService(_Spheres({1: site}), _Directory([]))

    result = service.read_site(1)

    assert result is site


def test_list_spheres_returns_directory_items():
    sphere = SimpleNamespace(pk=1, name="Root", domain="ludamus.example.com")
    service = SitesService(_Spheres({}), _Directory([sphere]))

    result = service.list_spheres()

    assert result == [sphere]
