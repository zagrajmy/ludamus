from types import SimpleNamespace

from ludamus.mills.multiverse import SitesService


class _Spheres:
    def __init__(self, *, sites, spheres=None, managers=()):
        self._sites = dict(sites)
        self._spheres = dict(spheres or {})
        self._managers = set(managers)

    def read_site(self, sphere_id):
        return self._sites[sphere_id]

    def read_with_site(self, sphere_id):
        return self._spheres[sphere_id], self._sites[sphere_id]

    def is_manager(self, sphere_id, user_slug):
        return (sphere_id, user_slug) in self._managers


class _Directory:
    def __init__(self, spheres):
        self._spheres = list(spheres)

    def list_all(self):
        return list(self._spheres)


def test_read_site_returns_repo_site():
    site = SimpleNamespace(domain="ludamus.example.com", name="Root", pk=7)
    service = SitesService(_Spheres(sites={1: site}), _Directory([]))

    result = service.read_site(1)

    assert result is site


def test_read_with_site_returns_sphere_and_site():
    sphere = SimpleNamespace(pk=1, name="Root")
    site = SimpleNamespace(domain="ludamus.example.com", name="Root", pk=1)
    service = SitesService(
        _Spheres(sites={1: site}, spheres={1: sphere}), _Directory([])
    )

    result = service.read_with_site(1)

    assert result == (sphere, site)


def test_is_manager_delegates_to_repo():
    service = SitesService(_Spheres(sites={}, managers={(1, "amy")}), _Directory([]))

    assert service.is_manager(1, "amy") is True
    assert service.is_manager(1, "bob") is False


def test_list_spheres_returns_directory_items():
    sphere = SimpleNamespace(pk=1, name="Root", domain="ludamus.example.com")
    service = SitesService(_Spheres(sites={}), _Directory([sphere]))

    result = service.list_spheres()

    assert result == [sphere]
