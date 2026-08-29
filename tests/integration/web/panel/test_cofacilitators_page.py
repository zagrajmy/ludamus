"""Integration tests for the co-facilitator extraction pages."""

from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import (
    Facilitator,
    PersonalDataField,
    PersonalDataFieldValue,
    SessionField,
    SessionFieldValue,
)
from ludamus.pacts import OrganizerFieldDTO
from ludamus.pacts.panel import (
    CofacilitatorCandidateDTO,
    CofacilitatorSessionDetailDTO,
    CofacilitatorSessionDTO,
)
from tests.integration.conftest import SessionFactory
from tests.integration.utils import assert_login_required, assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_not_a_manager,
    panel_context,
)


def _tab_urls(event):
    return {
        "list": reverse("panel:facilitators", kwargs={"slug": event.slug}),
        "merge": reverse("panel:facilitator-merge", kwargs={"slug": event.slug}),
        "columns": reverse("panel:facilitator-columns", kwargs={"slug": event.slug}),
        "bin": reverse("panel:facilitator-bin", kwargs={"slug": event.slug}),
        "cofacilitators": reverse("panel:cofacilitators", kwargs={"slug": event.slug}),
    }


def _field_dto(field):
    return OrganizerFieldDTO(
        field_type=field.field_type,
        is_multiple=field.is_multiple,
        name=field.name,
        options=[],
        order=field.order,
        pk=field.pk,
        question=field.question,
        slug=field.slug,
    )


def _detail(session, *, facilitators=(), linked=()):
    """Build the read aggregate the resolve page renders for the fixture."""
    return CofacilitatorSessionDetailDTO(
        session_id=session.pk,
        title="Dungeon",
        value="Jan Kowalski i Piotr Nowak",
        facilitators=list(facilitators),
        candidates=[
            CofacilitatorCandidateDTO(
                index=index,
                name=name,
                values={},
                match=None,
                already_linked=name in linked,
            )
            for index, name in enumerate(["Jan Kowalski", "Piotr Nowak"])
        ],
        personal_fields=[],
    )


def _event_context(event):
    return {
        **panel_context(event, active_nav="facilitators"),
        "active_tab": "cofacilitators",
        "tab_urls": _tab_urls(event),
    }


@pytest.fixture(name="cohost_field")
def cohost_field_fixture(event):
    return SessionField.objects.create(
        event=event,
        name="Co-facilitators",
        question="Who runs it with you?",
        slug="co-facilitators",
    )


@pytest.fixture(name="session_with_answer")
def session_with_answer_fixture(event, cohost_field):
    session = SessionFactory(event=event, category=None, title="Dungeon")
    SessionFieldValue.objects.create(
        session=session, field=cohost_field, value="Jan Kowalski i Piotr Nowak"
    )
    return session


class TestCofacilitatorsPageView:
    """Tests for /panel/event/<slug>/facilitators/co-facilitators/ page."""

    @staticmethod
    def get_url(event):
        return reverse("panel:cofacilitators", kwargs={"slug": event.slug})

    def test_get_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_login_required(response, url)

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_not_a_manager(response)

    def test_get_redirects_when_event_not_found(self, panel_client):
        url = reverse("panel:cofacilitators", kwargs={"slug": "nonexistent"})

        response = panel_client.get(url)

        assert_event_not_found(response)

    def test_get_lists_the_sessions_that_still_name_people(
        self, panel_client, event, cohost_field, session_with_answer
    ):
        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cofacilitators.html",
            context_data={
                **_event_context(event),
                "fields": [_field_dto(cohost_field)],
                "chosen_field": _field_dto(cohost_field),
                "sessions": [
                    CofacilitatorSessionDTO(
                        session_id=session_with_answer.pk,
                        title="Dungeon",
                        value="Jan Kowalski i Piotr Nowak",
                        facilitator_names=[],
                        unresolved_count=2,
                    )
                ],
            },
        )

    def test_get_counts_only_the_people_still_missing(
        self, panel_client, event, cohost_field, session_with_answer
    ):
        already = Facilitator.objects.create(
            event=event, display_name="Piotr Nowak", slug="piotr-nowak"
        )
        session_with_answer.facilitators.add(already)

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cofacilitators.html",
            context_data={
                **_event_context(event),
                "fields": [_field_dto(cohost_field)],
                "chosen_field": _field_dto(cohost_field),
                "sessions": [
                    CofacilitatorSessionDTO(
                        session_id=session_with_answer.pk,
                        title="Dungeon",
                        value="Jan Kowalski i Piotr Nowak",
                        facilitator_names=["Piotr Nowak"],
                        unresolved_count=1,
                    )
                ],
            },
        )

    def test_get_shows_no_sessions_when_the_event_has_no_fields(
        self, panel_client, event
    ):
        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cofacilitators.html",
            context_data={
                **_event_context(event),
                "fields": [],
                "chosen_field": None,
                "sessions": [],
            },
        )

    def test_get_skips_a_session_whose_answer_is_empty(
        self, panel_client, event, cohost_field
    ):
        session = SessionFactory(event=event, category=None)
        SessionFieldValue.objects.create(session=session, field=cohost_field, value="")

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cofacilitators.html",
            context_data={
                **_event_context(event),
                "fields": [_field_dto(cohost_field)],
                "chosen_field": _field_dto(cohost_field),
                "sessions": [],
            },
        )


class TestCofacilitatorResolvePageView:
    """Tests for the per-session resolve page."""

    @staticmethod
    def get_url(event, session, field=None):
        url = reverse(
            "panel:cofacilitator-resolve",
            kwargs={"slug": event.slug, "session_id": session.pk},
        )
        return f"{url}?field={field.pk}" if field else url

    def test_get_redirects_anonymous_user_to_login(
        self, client, event, session_with_answer
    ):
        url = self.get_url(event, session_with_answer)

        response = client.get(url)

        assert_login_required(response, url)

    def test_get_redirects_non_manager_user(
        self, authenticated_client, event, session_with_answer, cohost_field
    ):
        response = authenticated_client.get(
            self.get_url(event, session_with_answer, cohost_field)
        )

        assert_not_a_manager(response)

    def test_get_offers_one_row_per_person_the_answer_names(
        self, panel_client, event, session_with_answer, cohost_field
    ):
        response = panel_client.get(
            self.get_url(event, session_with_answer, cohost_field)
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cofacilitator-resolve.html",
            context_data={
                **_event_context(event),
                "session": _detail(session_with_answer),
                "chosen_field": _field_dto(cohost_field),
                "rows": ANY,
                "existing_facilitators": [],
            },
        )

    def test_get_marks_a_person_already_on_the_session(
        self, panel_client, event, session_with_answer, cohost_field
    ):
        already = Facilitator.objects.create(
            event=event, display_name="Piotr Nowak", slug="piotr-nowak"
        )
        session_with_answer.facilitators.add(already)

        response = panel_client.get(
            self.get_url(event, session_with_answer, cohost_field)
        )

        candidates = response.context["session"].candidates
        assert [(c.name, c.already_linked) for c in candidates] == [
            ("Jan Kowalski", False),
            ("Piotr Nowak", True),
        ]
        assert [row["target"] for row in response.context["rows"]] == ["new", "skip"]

    def test_get_redirects_a_session_from_another_event(
        self, panel_client, event, cohost_field
    ):
        other_session = SessionFactory(category=None)

        response = panel_client.get(self.get_url(event, other_session, cohost_field))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Session not found.")],
            url=reverse("panel:cofacilitators", kwargs={"slug": event.slug}),
        )

    def test_post_creates_the_people_the_organizer_confirmed(
        self, panel_client, event, session_with_answer, cohost_field
    ):
        response = panel_client.post(
            self.get_url(event, session_with_answer, cohost_field),
            data={
                "field": cohost_field.pk,
                "cofacilitator0_target": "new",
                "cofacilitator0_name": "Jan Kowalski",
                "cofacilitator1_target": "skip",
                "cofacilitator1_name": "Piotr Nowak",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "1 facilitator added to the session.")],
            url=self.get_url(event, session_with_answer, cohost_field),
        )
        assert [f.display_name for f in session_with_answer.facilitators.all()] == [
            "Jan Kowalski"
        ]
        assert not Facilitator.objects.filter(display_name="Piotr Nowak").exists()

    def test_post_links_an_existing_facilitator_instead_of_minting_one(
        self, panel_client, event, session_with_answer, cohost_field
    ):
        existing = Facilitator.objects.create(
            event=event, display_name="Piotr Nowak", slug="piotr-nowak"
        )

        panel_client.post(
            self.get_url(event, session_with_answer, cohost_field),
            data={
                "field": cohost_field.pk,
                "cofacilitator0_target": "skip",
                "cofacilitator1_target": "existing",
                "cofacilitator1_existing": existing.pk,
            },
        )

        assert list(session_with_answer.facilitators.all()) == [existing]
        assert Facilitator.objects.filter(event=event).count() == 1

    def test_post_refuses_a_facilitator_from_another_event(
        self, panel_client, event, session_with_answer, cohost_field
    ):
        foreign = Facilitator.objects.create(
            event=SessionFactory(category=None).event,
            display_name="Foreign",
            slug="foreign",
        )

        response = panel_client.post(
            self.get_url(event, session_with_answer, cohost_field),
            data={
                "field": cohost_field.pk,
                "cofacilitator0_target": "skip",
                "cofacilitator1_target": "existing",
                "cofacilitator1_existing": foreign.pk,
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Facilitator not found.")],
            url=reverse("panel:cofacilitators", kwargs={"slug": event.slug}),
        )
        assert not session_with_answer.facilitators.exists()

    def test_post_stores_the_personal_data_of_a_new_facilitator(
        self, panel_client, event, session_with_answer, cohost_field
    ):
        first_name = PersonalDataField.objects.create(
            event=event, name="Imię", question="Imię?", slug="imie"
        )

        panel_client.post(
            self.get_url(event, session_with_answer, cohost_field),
            data={
                "field": cohost_field.pk,
                "cofacilitator0_target": "new",
                "cofacilitator0_name": 'John "Wildstyle" Smith',
                "cofacilitator0_imie": "John",
                "cofacilitator1_target": "skip",
            },
        )

        facilitator = Facilitator.objects.get(display_name='John "Wildstyle" Smith')
        assert (
            PersonalDataFieldValue.objects.get(
                facilitator=facilitator, field=first_name
            ).value
            == "John"
        )

    def test_post_reports_a_row_left_without_a_name(
        self, panel_client, event, session_with_answer, cohost_field
    ):
        response = panel_client.post(
            self.get_url(event, session_with_answer, cohost_field),
            data={
                "field": cohost_field.pk,
                "cofacilitator0_target": "new",
                "cofacilitator0_name": "  ",
                "cofacilitator1_target": "skip",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/cofacilitator-resolve.html",
            context_data={
                **_event_context(event),
                "session": _detail(session_with_answer),
                "chosen_field": _field_dto(cohost_field),
                "rows": ANY,
                "existing_facilitators": [],
            },
        )
        assert not session_with_answer.facilitators.exists()


class TestCofacilitatorClearActionView:
    """Tests for the button that empties a resolved answer."""

    @staticmethod
    def get_url(event, session):
        return reverse(
            "panel:cofacilitator-clear",
            kwargs={"slug": event.slug, "session_id": session.pk},
        )

    def test_post_redirects_non_manager_user(
        self, authenticated_client, event, session_with_answer
    ):
        response = authenticated_client.post(
            self.get_url(event, session_with_answer), data={}
        )

        assert_not_a_manager(response)

    def test_post_empties_the_answer(
        self, panel_client, event, session_with_answer, cohost_field
    ):
        response = panel_client.post(
            self.get_url(event, session_with_answer), data={"field": cohost_field.pk}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Answer cleared.")],
            url=(
                reverse("panel:cofacilitators", kwargs={"slug": event.slug})
                + f"?field={cohost_field.pk}"
            ),
        )
        assert not SessionFieldValue.objects.filter(
            session=session_with_answer, field=cohost_field
        ).exists()

    def test_post_refuses_a_field_from_another_event(
        self, panel_client, event, session_with_answer, cohost_field
    ):
        foreign_field = SessionField.objects.create(
            event=SessionFactory(category=None).event,
            name="Other",
            question="Other?",
            slug="other",
        )

        response = panel_client.post(
            self.get_url(event, session_with_answer), data={"field": foreign_field.pk}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Session not found.")],
            url=reverse("panel:cofacilitators", kwargs={"slug": event.slug}),
        )
        assert SessionFieldValue.objects.filter(
            session=session_with_answer, field=cohost_field
        ).exists()
