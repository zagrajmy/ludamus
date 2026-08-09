from unittest.mock import MagicMock

import pytest

from ludamus.mills.multiverse import SpherePanelService
from ludamus.pacts.multiverse import Capability, SphereRole


@pytest.fixture(name="spheres")
def spheres_fixture():
    return MagicMock()


@pytest.fixture(name="service")
def service_fixture(spheres):
    return SpherePanelService(MagicMock(), spheres, MagicMock())


class TestSpherePanelServiceCan:
    def test_manager_holds_panel_write(self, service, spheres):
        spheres.manager_role.return_value = SphereRole.MANAGER

        assert (
            service.can(
                sphere_id=3, user_slug="boss", capability=Capability.PANEL_WRITE
            )
            is True
        )

    def test_comms_does_not_hold_panel_write(self, service, spheres):
        spheres.manager_role.return_value = SphereRole.COMMS

        assert (
            service.can(
                sphere_id=3, user_slug="press", capability=Capability.PANEL_WRITE
            )
            is False
        )

    def test_stranger_holds_nothing(self, service, spheres):
        spheres.manager_role.return_value = None

        assert (
            service.can(
                sphere_id=3, user_slug="passer-by", capability=Capability.PANEL_WRITE
            )
            is False
        )
