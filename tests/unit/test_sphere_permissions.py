from unittest.mock import MagicMock

import pytest

from ludamus.mills.multiverse import SpherePanelService
from ludamus.pacts.legacy import EncountersPolicy
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

    def test_the_role_is_looked_up_once(self, service, spheres):
        spheres.manager_role.return_value = SphereRole.MANAGER

        service.access(3, "boss")

        spheres.manager_role.assert_called_once_with(3, "boss")


class TestSpherePanelServiceUpdateSettings:
    def test_writes_the_policy(self, service, spheres):
        outcome = service.update_settings(
            3,
            allow_facilitator_session_edit=True,
            encounters_policy=EncountersPolicy.MANAGERS,
        )

        assert outcome is SphereSettingsOutcome.SAVED
        spheres.update.assert_called_once_with(
            3, {"allow_facilitator_session_edit": True, "encounters_policy": "managers"}
        )

    def test_logo_included_only_when_given(self, service, spheres):
        service.update_settings(
            3,
            allow_facilitator_session_edit=False,
            encounters_policy=EncountersPolicy.EVERYONE,
            logo="",
        )

        assert not spheres.update.call_args.args[1]["logo"]

    def test_refuses_to_hide_existing_encounters_unconfirmed(
        self, service, spheres, encounters
    ):
        spheres.read.return_value.encounters_policy = EncountersPolicy.EVERYONE
        encounters.exists_for_sphere.return_value = True

        outcome = service.update_settings(
            3,
            allow_facilitator_session_edit=True,
            encounters_policy=EncountersPolicy.NONE,
        )

        assert outcome is SphereSettingsOutcome.NEEDS_CONFIRMATION
        spheres.update.assert_not_called()

    def test_hides_them_once_confirmed(self, service, spheres, encounters):
        spheres.read.return_value.encounters_policy = EncountersPolicy.EVERYONE
        encounters.exists_for_sphere.return_value = True

        outcome = service.update_settings(
            3,
            allow_facilitator_session_edit=True,
            encounters_policy=EncountersPolicy.NONE,
            confirmed_encounters_disable=True,
        )

        assert outcome is SphereSettingsOutcome.SAVED
        spheres.update.assert_called_once()
