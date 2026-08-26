from unittest.mock import MagicMock

import pytest

from ludamus.mills.multiverse import SpherePanelService
from ludamus.pacts.legacy import EncounterPublicPolicy, SpherePage
from ludamus.pacts.multiverse import Capability, SphereRole


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


class TestSpherePanelServicePagesWithContent:
    @pytest.mark.parametrize(
        ("has_events", "has_encounters", "expected"),
        (
            (False, False, set()),
            (True, False, {SpherePage.EVENTS, SpherePage.TIMELINE}),
            (False, True, {SpherePage.ENCOUNTERS, SpherePage.TIMELINE}),
            (
                True,
                True,
                {SpherePage.EVENTS, SpherePage.ENCOUNTERS, SpherePage.TIMELINE},
            ),
        ),
    )
    def test_reports_pages_backed_by_rows(
        self, service, events, encounters, has_events, has_encounters, expected
    ):
        events.exists_for_sphere.return_value = has_events
        encounters.exists_for_sphere.return_value = has_encounters

        assert service.pages_with_content(3) == expected


class TestSpherePanelServiceUpdateSettings:
    def test_writes_pages_and_policy(self, service, spheres):
        service.update_settings(
            3,
            allow_facilitator_session_edit=True,
            enabled_pages=[SpherePage.ENCOUNTERS],
            default_page=SpherePage.ENCOUNTERS,
            encounter_public_policy=EncounterPublicPolicy.MANAGERS,
        )

        spheres.update.assert_called_once_with(
            3,
            {
                "allow_facilitator_session_edit": True,
                "enabled_pages": ["encounters"],
                "default_page": "encounters",
                "encounter_public_policy": "managers",
            },
        )

    def test_logo_included_only_when_given(self, service, spheres):
        service.update_settings(
            3,
            allow_facilitator_session_edit=False,
            enabled_pages=[SpherePage.EVENTS],
            default_page=SpherePage.EVENTS,
            encounter_public_policy=EncounterPublicPolicy.DISABLED,
            logo="",
        )

        assert not spheres.update.call_args.args[1]["logo"]
