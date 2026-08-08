from types import SimpleNamespace

from ludamus.mills.multiverse import SitesService


class _Spheres:
    def __init__(self, *, spheres=None):
        self._spheres = dict(spheres or {})

    def read(self, sphere_id):
        return self._spheres[sphere_id]


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


def test_list_spheres_returns_directory_items():
    sphere = SimpleNamespace(pk=1, name="Root", domain="ludamus.example.com")
    service = SitesService(_Spheres(), _Directory([sphere]))

    result = service.list_spheres()

    assert result == [sphere]
