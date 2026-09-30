from contextlib import contextmanager
from datetime import UTC, datetime

from ludamus.mills.multiverse import SpherePanelService, can_write_programme
from ludamus.pacts.encounter import EncountersPolicy
from ludamus.pacts.legacy import EventDTO, SiteDTO, SphereDTO
from ludamus.pacts.multiverse import (
    Capability,
    SphereRole,
    SphereSettingsOutcome,
    SphereVisibility,
)
from tests.unit.factories import user_dto

SPHERE_PK = 3
OTHER_SPHERE_PK = 4
_NOW = datetime(2026, 5, 1, 12, tzinfo=UTC)


class FakeTransaction:
    @contextmanager
    def atomic(self):
        yield


def _sphere(pk=SPHERE_PK, **overrides):
    return SphereDTO(
        name="Sfera",
        pk=pk,
        site=SiteDTO(domain="sfera.example.net", name="Sfera", pk=pk),
        **overrides,
    )


def _event(pk=1):
    return EventDTO(
        description="",
        end_time=_NOW,
        name="Konwencik",
        pk=pk,
        proposal_end_time=None,
        proposal_start_time=None,
        publication_time=None,
        slug="konwencik",
        sphere_id=SPHERE_PK,
        start_time=_NOW,
    )


class FakeSpheres:
    def __init__(self, sphere=None, *, roles=None):
        self.sphere = sphere or _sphere()
        self.roles = roles or {}
        self.updates = []

    def manager_role(self, sphere_id, user_slug):
        return self.roles.get((sphere_id, user_slug))

    def read(self, sphere_id):
        assert sphere_id == self.sphere.pk
        return self.sphere

    def update(self, sphere_id, data):
        self.updates.append((sphere_id, dict(data)))


class FakeEvents:
    @staticmethod
    def list_by_sphere(sphere_id):
        return [_event()] if sphere_id == SPHERE_PK else []


class FakeEncounters:
    def __init__(self, *, exists=False):
        self._exists = exists

    def exists_for_sphere(self, sphere_id):
        return self._exists and sphere_id == SPHERE_PK


class FakeUsers:
    def __init__(self, *users):
        self._users = {user.slug: user for user in users}

    def read(self, slug):
        return self._users[slug]


def _service(*, spheres=None, encounters=None, users=None):
    return SpherePanelService(
        FakeTransaction(),
        spheres or FakeSpheres(),
        FakeEvents(),
        encounters or FakeEncounters(),
        users or FakeUsers(),
    )


class TestSpherePanelServiceAccess:
    def test_manager_holds_panel_write(self):
        spheres = FakeSpheres(roles={(SPHERE_PK, "boss"): SphereRole.MANAGER})

        access = _service(spheres=spheres).access(SPHERE_PK, "boss")

        assert access.role is SphereRole.MANAGER
        assert Capability.PANEL_WRITE in access.capabilities

    def test_comms_holds_the_acknowledgement_but_not_panel_write(self):
        spheres = FakeSpheres(roles={(SPHERE_PK, "press"): SphereRole.COMMS})

        access = _service(spheres=spheres).access(SPHERE_PK, "press")

        assert access.capabilities == frozenset({Capability.ERRATUM_ACK})

    def test_stranger_holds_nothing(self):
        access = _service().access(SPHERE_PK, "passer-by")

        assert access.role is None
        assert not access.capabilities

    def test_manager_role_is_scoped_to_the_sphere(self):
        spheres = FakeSpheres(roles={(SPHERE_PK, "boss"): SphereRole.MANAGER})
        service = _service(spheres=spheres)

        assert service.manager_role(SPHERE_PK, "boss") is SphereRole.MANAGER
        assert service.manager_role(OTHER_SPHERE_PK, "boss") is None


class TestCanWriteProgramme:
    def test_superuser_writes_anywhere(self):
        users = FakeUsers(user_dto(slug="root", is_superuser=True))

        assert can_write_programme(
            users=users, spheres=FakeSpheres(), sphere_id=SPHERE_PK, user_slug="root"
        )

    def test_manager_writes_only_their_sphere(self):
        users = FakeUsers(user_dto(slug="boss"))
        spheres = FakeSpheres(roles={(SPHERE_PK, "boss"): SphereRole.MANAGER})
        service = _service(spheres=spheres, users=users)

        assert service.can_write_programme(SPHERE_PK, "boss") is True
        assert service.can_write_programme(OTHER_SPHERE_PK, "boss") is False

    def test_comms_member_reads_only(self):
        users = FakeUsers(user_dto(slug="press"))
        spheres = FakeSpheres(roles={(SPHERE_PK, "press"): SphereRole.COMMS})

        assert (
            _service(spheres=spheres, users=users).can_write_programme(
                SPHERE_PK, "press"
            )
            is False
        )


class TestSpherePanelServiceReads:
    def test_list_events_for_the_sphere(self):
        service = _service()

        assert service.list_events(SPHERE_PK) == [_event()]
        assert service.list_events(OTHER_SPHERE_PK) == []

    def test_read_returns_the_sphere(self):
        assert _service().read(SPHERE_PK) == _sphere()


class TestSpherePanelServiceUpdateSettings:
    @staticmethod
    def _update(service, **overrides):
        kwargs = {
            "allow_facilitator_session_edit": False,
            "event_cover_buttons_at_bottom": True,
            "encounters_policy": EncountersPolicy.MANAGERS,
        }
        return service.update_settings(SPHERE_PK, **(kwargs | overrides))

    def test_saves_every_named_field_and_keeps_the_logo(self):
        spheres = FakeSpheres()

        outcome = self._update(_service(spheres=spheres))

        assert outcome is SphereSettingsOutcome.SAVED
        assert spheres.updates == [
            (
                SPHERE_PK,
                {
                    "allow_facilitator_session_edit": False,
                    "event_cover_buttons_at_bottom": True,
                    "encounters_policy": "managers",
                },
            )
        ]

    def test_empty_logo_removes_it(self):
        spheres = FakeSpheres()

        self._update(_service(spheres=spheres), logo="")

        assert spheres.updates[0][1] == {
            "allow_facilitator_session_edit": False,
            "event_cover_buttons_at_bottom": True,
            "encounters_policy": "managers",
            "logo": "",
        }

    def test_refuses_to_hide_existing_encounters_unconfirmed(self):
        spheres = FakeSpheres(_sphere(encounters_policy=EncountersPolicy.EVERYONE))
        service = _service(spheres=spheres, encounters=FakeEncounters(exists=True))

        outcome = self._update(service, encounters_policy=EncountersPolicy.NONE)

        assert outcome is SphereSettingsOutcome.NEEDS_CONFIRMATION
        assert not spheres.updates

    def test_confirmed_hide_is_saved(self):
        spheres = FakeSpheres(_sphere(encounters_policy=EncountersPolicy.EVERYONE))
        service = _service(spheres=spheres, encounters=FakeEncounters(exists=True))

        outcome = self._update(
            service,
            encounters_policy=EncountersPolicy.NONE,
            confirmed_encounters_disable=True,
        )

        assert outcome is SphereSettingsOutcome.SAVED
        assert spheres.updates[0][1]["encounters_policy"] == "none"

    def test_hiding_with_nothing_to_hide_needs_no_confirmation(self):
        spheres = FakeSpheres(_sphere(encounters_policy=EncountersPolicy.EVERYONE))

        outcome = self._update(
            _service(spheres=spheres), encounters_policy=EncountersPolicy.NONE
        )

        assert outcome is SphereSettingsOutcome.SAVED


class TestSpherePanelServicePatchSettings:
    def test_a_patch_writes_only_what_it_names(self):
        # The point of the patch shape: a caller changing one setting must not
        # carry the others along, because it would be carrying whatever it
        # read a moment ago and overwriting a change made in between.
        spheres = FakeSpheres()

        _service(spheres=spheres).patch_settings(
            SPHERE_PK, changes={"encounters_policy": EncountersPolicy.MANAGERS}
        )

        assert spheres.updates == [(SPHERE_PK, {"encounters_policy": "managers"})]

    def test_every_flag_is_carried_when_named(self):
        spheres = FakeSpheres()

        outcome = _service(spheres=spheres).patch_settings(
            SPHERE_PK,
            changes={
                "allow_facilitator_session_edit": False,
                "event_cover_buttons_at_bottom": True,
                "visibility": SphereVisibility.PRIVATE,
            },
        )

        assert outcome is SphereSettingsOutcome.SAVED
        assert spheres.updates == [
            (
                SPHERE_PK,
                {
                    "allow_facilitator_session_edit": False,
                    "event_cover_buttons_at_bottom": True,
                    "visibility": SphereVisibility.PRIVATE,
                },
            )
        ]

    def test_an_empty_patch_writes_nothing(self):
        spheres = FakeSpheres()

        outcome = _service(spheres=spheres).patch_settings(SPHERE_PK, changes={})

        assert outcome is SphereSettingsOutcome.SAVED
        assert not spheres.updates

    def test_refuses_to_hide_existing_encounters_unconfirmed(self):
        spheres = FakeSpheres(_sphere(encounters_policy=EncountersPolicy.EVERYONE))
        service = _service(spheres=spheres, encounters=FakeEncounters(exists=True))

        outcome = service.patch_settings(
            SPHERE_PK, changes={"encounters_policy": EncountersPolicy.NONE}
        )

        assert outcome is SphereSettingsOutcome.NEEDS_CONFIRMATION
        assert not spheres.updates

    def test_confirmed_hide_is_saved(self):
        spheres = FakeSpheres(_sphere(encounters_policy=EncountersPolicy.EVERYONE))
        service = _service(spheres=spheres, encounters=FakeEncounters(exists=True))

        outcome = service.patch_settings(
            SPHERE_PK,
            changes={"encounters_policy": EncountersPolicy.NONE},
            confirmed_encounters_disable=True,
        )

        assert outcome is SphereSettingsOutcome.SAVED
        assert spheres.updates == [(SPHERE_PK, {"encounters_policy": "none"})]


def test_update_logo_writes_only_the_logo():
    spheres = FakeSpheres()

    _service(spheres=spheres).update_logo(SPHERE_PK, "")

    assert spheres.updates == [(SPHERE_PK, {"logo": ""})]
