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


class TestSpherePanelServiceAccess:
    def test_manager_holds_panel_write(self, service, spheres):
        spheres.manager_role.return_value = SphereRole.MANAGER

        access = service.access(3, "boss")

        assert access.role is SphereRole.MANAGER
        assert Capability.PANEL_WRITE in access.capabilities

    def test_comms_holds_the_acknowledgement_but_not_panel_write(
        self, service, spheres
    ):
        spheres.manager_role.return_value = SphereRole.COMMS

        access = service.access(3, "press")

        assert access.capabilities == frozenset({Capability.ERRATUM_ACK})

    def test_stranger_holds_nothing(self, service, spheres):
        spheres.manager_role.return_value = None

        access = service.access(3, "passer-by")

        assert access.role is None
        assert not access.capabilities

    def test_the_role_is_looked_up_once(self, service, spheres):
        spheres.manager_role.return_value = SphereRole.MANAGER

        service.access(3, "boss")

        spheres.manager_role.assert_called_once_with(3, "boss")
