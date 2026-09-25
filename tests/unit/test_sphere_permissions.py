from unittest.mock import MagicMock

import pytest

from ludamus.mills.multiverse import SpherePanelService
from ludamus.pacts.encounter import EncountersPolicy
from ludamus.pacts.multiverse import Capability, SphereRole, SphereSettingsOutcome


@pytest.fixture(name="spheres")
def spheres_fixture():
    return MagicMock()


@pytest.fixture(name="events")
def events_fixture():
    return MagicMock()


@pytest.fixture(name="encounters")
def encounters_fixture():
    return MagicMock()


@pytest.fixture(name="service")
def service_fixture(spheres, events, encounters):
    return SpherePanelService(MagicMock(), spheres, events, encounters)


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


class TestSpherePanelServicePatchSettings:
    def test_a_patch_writes_only_what_it_names(self, service, spheres):
        # The point of the patch shape: a caller changing one setting must not
        # carry the others along, because it would be carrying whatever it
        # read a moment ago and overwriting a change made in between.
        service.patch_settings(
            3, changes={"encounters_policy": EncountersPolicy.MANAGERS}
        )

        spheres.update.assert_called_once_with(3, {"encounters_policy": "managers"})

    def test_refuses_to_hide_existing_encounters_unconfirmed(
        self, service, spheres, encounters
    ):
        spheres.read.return_value.encounters_policy = EncountersPolicy.EVERYONE
        encounters.exists_for_sphere.return_value = True

        outcome = service.patch_settings(
            3, changes={"encounters_policy": EncountersPolicy.NONE}
        )

        assert outcome is SphereSettingsOutcome.NEEDS_CONFIRMATION
        spheres.update.assert_not_called()
