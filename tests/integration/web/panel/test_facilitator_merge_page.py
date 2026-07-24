"""Integration tests for the facilitator merge page."""

from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.gates.web.django.forms import ACCREDITATION_TYPE_LABELS
from ludamus.links.db.django.models import Facilitator, ProposalCategory, Session
from ludamus.pacts import EventDTO, FacilitatorListItemDTO
from ludamus.pacts.submissions import AccreditationType, FacilitatorColumnDTO
from tests.integration.conftest import EventFactory, UserFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."

_DEFAULT_COLUMNS = [
    FacilitatorColumnDTO(key=key)
    for key in ("name", "linked", "sessions", "accreditation", "organizer")
]


def _make_facilitator(event, display_name, slug):
    return Facilitator.objects.create(
        event=event, display_name=display_name, slug=slug, user=None
    )


def _column_values(facilitators):
    return {
        facilitator.pk: {
            "name": facilitator.display_name,
            "linked": "Linked" if facilitator.user_id else "None",
            "sessions": str(facilitator.session_count),
            "accreditation": str(
                ACCREDITATION_TYPE_LABELS[
                    AccreditationType(facilitator.accreditation_type)
                ]
            ),
            "organizer": facilitator.organizer_name or "—",
        }
        for facilitator in facilitators
    }


def _base_context(event):
    return {
        "current_event": EventDTO.model_validate(event),
        "events": [EventDTO.model_validate(event)],
        "is_proposal_active": False,
        "stats": {
            "hosts_count": 0,
            "pending_proposals": 0,
            "rooms_count": 0,
            "scheduled_sessions": 0,
            "total_proposals": 0,
            "total_sessions": 0,
        },
        "active_nav": "facilitators",
        "active_tab": "merge",
        "columns": _DEFAULT_COLUMNS,
        "tab_urls": {
            "list": reverse("panel:facilitators", kwargs={"slug": event.slug}),
            "merge": reverse("panel:facilitator-merge", kwargs={"slug": event.slug}),
            "columns": reverse(
                "panel:facilitator-columns", kwargs={"slug": event.slug}
            ),
        },
    }


class TestFacilitatorMergePageView:
    """Tests for /panel/event/<slug>/facilitators/merge/ page."""

    @staticmethod
    def get_url(event):
        return reverse("panel:facilitator-merge", kwargs={"slug": event.slug})

    def test_get_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_get_redirects_when_event_not_found(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:facilitator-merge", kwargs={"slug": "nonexistent"})

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url=reverse("panel:index"),
        )

    def test_get_ok_for_sphere_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-merge.html",
            context_data={
                **_base_context(event),
                "facilitators": [],
                "column_values": {},
                "preselected_ids": set(),
                "error": None,
            },
        )

    def test_get_preselects_ids_from_query_params(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        f1 = _make_facilitator(event, "Alice", "alice")
        f2 = _make_facilitator(event, "Bob", "bob")

        response = authenticated_client.get(
            self.get_url(event), data={"ids": [f1.pk, f2.pk]}
        )

        expected = [
            FacilitatorListItemDTO(
                accreditation_type="none",
                display_name="Alice",
                pk=f1.pk,
                slug="alice",
                user_id=None,
                session_count=0,
            ),
            FacilitatorListItemDTO(
                accreditation_type="none",
                display_name="Bob",
                pk=f2.pk,
                slug="bob",
                user_id=None,
                session_count=0,
            ),
        ]
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-merge.html",
            context_data={
                **_base_context(event),
                "facilitators": expected,
                "column_values": _column_values(expected),
                "preselected_ids": {f1.pk, f2.pk},
                "error": None,
            },
        )

    def test_post_redirects_when_event_not_found(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:facilitator-merge", kwargs={"slug": "nonexistent"})

        response = authenticated_client.post(url, data={})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url=reverse("panel:index"),
        )

    def test_post_merges_facilitators_and_redirects(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        target = _make_facilitator(event, "Alice", "alice")
        source = _make_facilitator(event, "Alice Duplicate", "alice-dup")
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        session = Session.objects.create(
            event=event,
            category=category,
            display_name="Alice Duplicate",
            title="A Session",
            slug="a-session",
            participants_limit=0,
            status="pending",
        )
        session.facilitators.add(source)

        response = authenticated_client.post(
            self.get_url(event),
            data={"facilitator_ids": [target.pk, source.pk], "target_id": target.pk},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Facilitators merged successfully.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )
        assert not Facilitator.objects.filter(pk=source.pk).exists()
        assert Facilitator.objects.filter(pk=target.pk).exists()
        assert list(session.facilitators.values_list("pk", flat=True)) == [target.pk]

    def test_post_keeps_the_only_organizer_among_merged(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        organizer = UserFactory(username="organizer", email="organizer@example.com")
        target = _make_facilitator(event, "Alice", "alice")
        source = _make_facilitator(event, "Alice Duplicate", "alice-dup")
        Facilitator.objects.filter(pk=source.pk).update(organizer=organizer)

        authenticated_client.post(
            self.get_url(event),
            data={"facilitator_ids": [target.pk, source.pk], "target_id": target.pk},
        )

        target.refresh_from_db()
        assert target.organizer_id == organizer.pk

    def test_post_clears_disagreeing_organizers(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        one = UserFactory(username="organizer-one", email="organizer1@example.com")
        two = UserFactory(username="organizer-two", email="organizer2@example.com")
        target = _make_facilitator(event, "Alice", "alice")
        source = _make_facilitator(event, "Alice Duplicate", "alice-dup")
        Facilitator.objects.filter(pk=target.pk).update(organizer=one)
        Facilitator.objects.filter(pk=source.pk).update(organizer=two)

        authenticated_client.post(
            self.get_url(event),
            data={"facilitator_ids": [target.pk, source.pk], "target_id": target.pk},
        )

        target.refresh_from_db()
        assert target.organizer_id is None

    def test_post_keeps_a_shared_organizer(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        organizer = UserFactory(username="organizer", email="organizer@example.com")
        target = _make_facilitator(event, "Alice", "alice")
        source = _make_facilitator(event, "Alice Duplicate", "alice-dup")
        Facilitator.objects.filter(pk__in=[target.pk, source.pk]).update(
            organizer=organizer
        )

        authenticated_client.post(
            self.get_url(event),
            data={"facilitator_ids": [target.pk, source.pk], "target_id": target.pk},
        )

        target.refresh_from_db()
        assert target.organizer_id == organizer.pk

    def test_post_rejects_merge_when_multiple_linked_users(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        user_1 = UserFactory(username="user-one", email="user1@example.com")
        user_2 = UserFactory(username="user-two", email="user2@example.com")
        f1 = _make_facilitator(event, "Alice", "alice")
        f2 = _make_facilitator(event, "Bob", "bob")
        Facilitator.objects.filter(pk=f1.pk).update(user=user_1)
        Facilitator.objects.filter(pk=f2.pk).update(user=user_2)

        response = authenticated_client.post(
            self.get_url(event),
            data={"facilitator_ids": [f1.pk, f2.pk], "target_id": f1.pk},
        )

        expected = [
            FacilitatorListItemDTO(
                accreditation_type="none",
                display_name="Alice",
                pk=f1.pk,
                slug="alice",
                user_id=user_1.pk,
                session_count=0,
            ),
            FacilitatorListItemDTO(
                accreditation_type="none",
                display_name="Bob",
                pk=f2.pk,
                slug="bob",
                user_id=user_2.pk,
                session_count=0,
            ),
        ]
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-merge.html",
            context_data={
                **_base_context(event),
                "facilitators": expected,
                "column_values": _column_values(expected),
                "preselected_ids": {f1.pk, f2.pk},
                "error": (
                    "Cannot merge facilitators that each have a linked user account."
                ),
            },
        )
        assert Facilitator.objects.filter(pk=f1.pk).exists()
        assert Facilitator.objects.filter(pk=f2.pk).exists()

    def test_post_ignores_foreign_facilitators_in_selection(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        local = _make_facilitator(event, "Alice", "alice")
        other_event = EventFactory(sphere=sphere)
        foreign_source = _make_facilitator(other_event, "Mallory", "mallory")
        foreign_target = _make_facilitator(other_event, "Trudy", "trudy")

        response = authenticated_client.post(
            self.get_url(event),
            data={
                "facilitator_ids": [local.pk, foreign_source.pk, foreign_target.pk],
                "target_id": foreign_target.pk,
            },
        )

        expected = [
            FacilitatorListItemDTO(
                accreditation_type="none",
                display_name="Alice",
                pk=local.pk,
                slug="alice",
                user_id=None,
                session_count=0,
            )
        ]
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-merge.html",
            context_data={
                **_base_context(event),
                "events": [
                    EventDTO.model_validate(other_event),
                    EventDTO.model_validate(event),
                ],
                "facilitators": expected,
                "column_values": _column_values(expected),
                "preselected_ids": {local.pk},
                "error": "Select at least two facilitators and choose a merge target.",
            },
        )
        assert Facilitator.objects.filter(pk=local.pk).exists()
        assert Facilitator.objects.filter(pk=foreign_source.pk).exists()
        assert Facilitator.objects.filter(pk=foreign_target.pk).exists()

    def test_post_rejects_insufficient_selection(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = _make_facilitator(event, "Alice", "alice")

        response = authenticated_client.post(
            self.get_url(event),
            data={"facilitator_ids": [facilitator.pk], "target_id": facilitator.pk},
        )

        expected = [
            FacilitatorListItemDTO(
                accreditation_type="none",
                display_name="Alice",
                pk=facilitator.pk,
                slug="alice",
                user_id=None,
                session_count=0,
            )
        ]
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-merge.html",
            context_data={
                **_base_context(event),
                "facilitators": expected,
                "column_values": _column_values(expected),
                "preselected_ids": {facilitator.pk},
                "error": "Select at least two facilitators and choose a merge target.",
            },
        )
