from types import SimpleNamespace

from ludamus.mills.multiverse import SitesService


class _Spheres:
    def __init__(self, *, spheres=None, managers=()):
        self._spheres = dict(spheres or {})
        self._managers = set(managers)

    def read(self, sphere_id):
        return self._spheres[sphere_id]

    def is_manager(self, sphere_id, user_slug):
        return (sphere_id, user_slug) in self._managers


class _Directory:
    def __init__(self, spheres):
        self._spheres = list(spheres)

    def list_all(self):
        return list(self._spheres)


def test_read_returns_repo_sphere():
    sphere = SimpleNamespace(pk=1, name="Root")
    service = SitesService(_Spheres(spheres={1: sphere}), _Directory([]))

    result = service.read(1)

    assert result is sphere


def test_is_manager_delegates_to_repo():
    service = SitesService(_Spheres(managers={(1, "amy")}), _Directory([]))

    assert service.is_manager(1, "amy") is True
    assert service.is_manager(1, "bob") is False


def test_list_spheres_returns_directory_items():
    sphere = SimpleNamespace(pk=1, name="Root", domain="ludamus.example.com")
    service = SitesService(_Spheres(), _Directory([sphere]))

    result = service.list_spheres()

    assert result == [sphere]
