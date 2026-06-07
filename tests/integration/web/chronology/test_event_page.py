import re
from datetime import UTC
from http import HTTPStatus
from unittest.mock import ANY

import pytest
import responses
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from ludamus.adapters.db.django.models import (
    DomainEnrollmentConfig,
    EnrollmentConfig,
    EventSettings,
    SessionField,
    SessionFieldValue,
    SessionParticipation,
    SessionParticipationStatus,
    UserEnrollmentConfig,
)
from ludamus.adapters.web.django.entities import (
    ParticipationInfo,
    SessionData,
    build_display_field_row,
)
from ludamus.gates.web.django.entities import UserInfo
from ludamus.links.gravatar import gravatar_url
from ludamus.pacts import (
    AgendaItemDTO,
    AreaDTO,
    LocationData,
    PendingSessionDTO,
    SessionDTO,
    SessionFieldValueDTO,
    SpaceDTO,
    UserDTO,
    VenueDTO,
    VirtualEnrollmentConfig,
)
from tests.integration.conftest import (
    AgendaItemFactory,
    EventFactory,
    ProposalCategoryFactory,
    SessionFactory,
    UserFactory,
)
from tests.integration.utils import assert_response

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01"
    b"\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
)


class TestEventPageView:
    URL_NAME = "web:chronology:event"

    def _get_url(self, slug: str) -> str:
        return reverse(self.URL_NAME, kwargs={"slug": slug})

    def test_ok(self, client, event):
        response = client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "current_hour_data": {},
                "ended_hour_data": {},
                "enrollment_requires_slots": False,
                "event": event,
                "filterable_tag_categories": [],
                "future_unavailable_hour_data": {},
                "hour_data": {},
                "object": event,
                "sessions": [],
                "user_enrollment_config": None,
                "total_enrolled": 0,
                "user_enrolled_sessions": [],
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )

    def test_ok_session_card_exposes_day_and_hour_data_attributes(
        self, active_user, agenda_item, client, event
    ):
        """Cards expose day/hour data attributes powering client-side filters."""
        session = agenda_item.session

        response = client.get(self._get_url(event.slug))

        session_data = SessionData(
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            full_participant_info="0/10",
            has_any_enrollments=False,
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(session),
            should_show_as_inactive=False,
            loc=LocationData(
                space=SpaceDTO.model_validate(agenda_item.space),
                area=AreaDTO.model_validate(agenda_item.space.area),
                venue=VenueDTO.model_validate(agenda_item.space.area.venue),
            ),
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "current_hour_data": {},
                "ended_hour_data": {},
                "enrollment_requires_slots": False,
                "event": event,
                "filterable_tag_categories": [],
                "future_unavailable_hour_data": {
                    agenda_item.start_time: [session_data]
                },
                "hour_data": {agenda_item.start_time: [session_data]},
                "object": event,
                "sessions": [session_data],
                "user_enrollment_config": None,
                "total_enrolled": 0,
                "user_enrolled_sessions": [],
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )
        local_start = timezone.localtime(agenda_item.start_time)
        content = response.content.decode()
        day = local_start.strftime("%Y-%m-%d")
        hour = local_start.strftime("%H:%M")
        match = re.search(
            rf'data-day="{re.escape(day)}"\s+data-day-label="([^"]+)"\s+data-hour="{re.escape(hour)}"',
            content,
        )
        assert match
        assert match.group(1)

    def test_shows_event_cover_image(self, client, event):
        event.cover_image = SimpleUploadedFile(
            "cover.png", PNG_BYTES, content_type="image/png"
        )
        event.save()

        response = client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "current_hour_data": {},
                "ended_hour_data": {},
                "enrollment_requires_slots": False,
                "event": event,
                "filterable_tag_categories": [],
                "future_unavailable_hour_data": {},
                "hour_data": {},
                "object": event,
                "sessions": [],
                "user_enrollment_config": None,
                "total_enrolled": 0,
                "user_enrolled_sessions": [],
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )
        assert event.cover_image_url.encode() in response.content

    @override_settings(MEDIA_URL="https://cdn.example.test/media/")
    def test_event_cover_image_used_as_absolute_social_metadata(self, client, event):
        event.cover_image = SimpleUploadedFile(
            "cover.png", PNG_BYTES, content_type="image/png"
        )
        event.save()

        response = client.get(self._get_url(event.slug))

        content = response.content.decode()
        absolute_url = event.cover_image_url
        assert absolute_url.startswith("http")
        assert absolute_url in content
        assert "zagrajmy.net/static/logo.png" not in content
        assert f"testserver{absolute_url}" not in content

    def test_session_card_shows_all_ages_when_min_age_zero(
        self, agenda_item, client, event
    ):
        session = agenda_item.session
        session.min_age = 0
        session.save()

        response = client.get(self._get_url(event.slug))

        assert response.status_code == HTTPStatus.OK
        assert b"All ages" in response.content

    def test_session_card_shows_overflow_tag_trigger(self, agenda_item, client, event):
        session_field = SessionField.objects.create(
            event=event,
            name="Genre",
            question="Genre",
            slug="genre",
            field_type="select",
            is_multiple=True,
            is_public=True,
        )
        session = agenda_item.session
        SessionFieldValue.objects.create(
            session=session, field=session_field, value=["a", "b", "c", "d", "e"]
        )
        settings, _ = EventSettings.objects.get_or_create(event=event)
        settings.displayed_session_fields.add(session_field)

        response = client.get(self._get_url(event.slug))

        assert response.status_code == HTTPStatus.OK
        assert b"session-tags-more" in response.content
        assert b"+1" in response.content

    def test_shows_session_cover_image(self, active_user, agenda_item, client, event):
        session = agenda_item.session
        session.cover_image = SimpleUploadedFile(
            "session.png", PNG_BYTES, content_type="image/png"
        )
        session.save()

        response = client.get(self._get_url(event.slug))

        session_data = SessionData(
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            full_participant_info="0/10",
            has_any_enrollments=False,
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(session),
            should_show_as_inactive=False,
            loc=LocationData(
                space=SpaceDTO.model_validate(agenda_item.space),
                area=AreaDTO.model_validate(agenda_item.space.area),
                venue=VenueDTO.model_validate(agenda_item.space.area.venue),
            ),
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "current_hour_data": {},
                "ended_hour_data": {},
                "enrollment_requires_slots": False,
                "event": event,
                "filterable_tag_categories": [],
                "future_unavailable_hour_data": {
                    agenda_item.start_time: [session_data]
                },
                "hour_data": {agenda_item.start_time: [session_data]},
                "object": event,
                "sessions": [session_data],
                "user_enrollment_config": None,
                "total_enrolled": 0,
                "user_enrolled_sessions": [],
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )
        assert session.cover_image_url.encode() in response.content

    def test_ok_superuser_proposal(
        self, authenticated_client, event, active_user, pending_session
    ):
        active_user.is_staff = True
        active_user.is_superuser = True
        active_user.save()
        response = authenticated_client.get(self._get_url(event.slug))

        expected_pending = PendingSessionDTO(
            contact_email=pending_session.contact_email,
            creation_time=pending_session.creation_time,
            description=pending_session.description,
            needs=pending_session.needs,
            participants_limit=pending_session.participants_limit,
            pk=pending_session.pk,
            display_name=pending_session.display_name,
            requirements=pending_session.requirements,
            tags=[],
            time_slots=[],
            title=pending_session.title,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "current_hour_data": {},
                "ended_hour_data": {},
                "enrollment_requires_slots": False,
                "event": event,
                "filterable_tag_categories": [],
                "future_unavailable_hour_data": {},
                "hour_data": {},
                "object": event,
                "pending_sessions": [expected_pending],
                "sessions": [],
                "user_enrollment_config": None,
                "total_enrolled": 0,
                "user_enrolled_sessions": [],
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )

    def test_ok_participations(
        self,
        authenticated_client,
        event,
        active_user,
        session,
        connected_user,
        agenda_item,
    ):
        part1 = SessionParticipation.objects.create(
            session=session,
            user=active_user,
            status=SessionParticipationStatus.CONFIRMED,
        )
        part2 = SessionParticipation.objects.create(
            session=session,
            user=connected_user,
            status=SessionParticipationStatus.WAITING,
        )
        active_user.is_staff = True
        active_user.is_superuser = True
        active_user.save()
        response = authenticated_client.get(self._get_url(event.slug))

        session_data = SessionData(
            can_edit=True,
            agenda_item=AgendaItemDTO.model_validate(session.agenda_item),
            effective_participants_limit=10,
            enrolled_count=1,
            waiting_count=1,
            full_participant_info="1/10, 1 waiting",
            has_any_enrollments=True,
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[
                ParticipationInfo(
                    user=UserInfo.from_user_dto(
                        UserDTO.model_validate(part1.user), gravatar_url=gravatar_url
                    ),
                    status=part1.status,
                    creation_time=part1.creation_time,
                ),
                ParticipationInfo(
                    user=UserInfo.from_user_dto(
                        UserDTO.model_validate(part2.user), gravatar_url=gravatar_url
                    ),
                    status=part2.status,
                    creation_time=part2.creation_time,
                ),
            ],
            session=SessionDTO.model_validate(session),
            should_show_as_inactive=False,
            loc=LocationData(
                space=SpaceDTO.model_validate(session.agenda_item.space),
                area=AreaDTO.model_validate(session.agenda_item.space.area),
                venue=VenueDTO.model_validate(session.agenda_item.space.area.venue),
            ),
            user_enrolled=True,
            user_waiting=True,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "current_hour_data": {},
                "ended_hour_data": {},
                "enrollment_requires_slots": False,
                "event": event,
                "filterable_tag_categories": [],
                "future_unavailable_hour_data": {
                    agenda_item.start_time: [session_data]
                },
                "hour_data": {agenda_item.start_time: [session_data]},
                "object": event,
                "pending_sessions": [],
                "sessions": [session_data],
                "user_enrollment_config": None,
                "total_enrolled": 1,
                "user_enrolled_sessions": [session_data],
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )
        assert "Connected Users" not in response.content.decode()

    def test_ok_session_with_linked_proposal(
        self, active_user, agenda_item, client, event, session
    ):
        host = UserInfo.from_user_dto(
            UserDTO.model_validate(active_user), gravatar_url=gravatar_url
        )
        session_data = SessionData(
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            full_participant_info="0/10",
            has_any_enrollments=False,
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=host,
            session_participations=[],
            session=SessionDTO.model_validate(session),
            should_show_as_inactive=False,
            loc=LocationData(
                space=SpaceDTO.model_validate(agenda_item.space),
                area=AreaDTO.model_validate(agenda_item.space.area),
                venue=VenueDTO.model_validate(agenda_item.space.area.venue),
            ),
            user_enrolled=False,
            user_waiting=False,
        )
        response = client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "current_hour_data": {},
                "ended_hour_data": {},
                "enrollment_requires_slots": False,
                "event": event,
                "filterable_tag_categories": [],
                "future_unavailable_hour_data": {
                    agenda_item.start_time: [session_data]
                },
                "hour_data": {agenda_item.start_time: [session_data]},
                "object": event,
                "sessions": [session_data],
                "user_enrollment_config": None,
                "total_enrolled": 0,
                "user_enrolled_sessions": [],
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )

    def test_ok_unlimited_session(
        self, active_user, agenda_item, client, event, session
    ):
        session.participants_limit = 0
        session.save()

        host = UserInfo.from_user_dto(
            UserDTO.model_validate(active_user), gravatar_url=gravatar_url
        )
        session_data = SessionData(
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=0,
            enrolled_count=0,
            full_participant_info="0",
            has_any_enrollments=False,
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=host,
            session_participations=[],
            session=SessionDTO.model_validate(session),
            should_show_as_inactive=False,
            loc=LocationData(
                space=SpaceDTO.model_validate(agenda_item.space),
                area=AreaDTO.model_validate(agenda_item.space.area),
                venue=VenueDTO.model_validate(agenda_item.space.area.venue),
            ),
            user_enrolled=False,
            user_waiting=False,
        )
        response = client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "current_hour_data": {},
                "ended_hour_data": {},
                "enrollment_requires_slots": False,
                "event": event,
                "filterable_tag_categories": [],
                "future_unavailable_hour_data": {
                    agenda_item.start_time: [session_data]
                },
                "hour_data": {agenda_item.start_time: [session_data]},
                "object": event,
                "sessions": [session_data],
                "user_enrollment_config": None,
                "total_enrolled": 0,
                "user_enrolled_sessions": [],
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )

    def test_ok_session_without_presenter_user(self, client, event, space, sphere):
        display_name = "External Presenter"
        session = SessionFactory(
            presenter=None,
            display_name=display_name,
            sphere=sphere,
            participants_limit=10,
            min_age=0,
        )
        agenda_item = AgendaItemFactory(session=session, space=space)

        response = client.get(self._get_url(event.slug))

        session_data = SessionData(
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            full_participant_info="0/10",
            has_any_enrollments=False,
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=UserInfo(
                avatar_url=None,
                discord_username="",
                full_name=display_name,
                name=display_name,
                pk=0,
                slug="",
                username=display_name,
            ),
            session_participations=[],
            session=SessionDTO.model_validate(session),
            should_show_as_inactive=False,
            loc=LocationData(
                space=SpaceDTO.model_validate(agenda_item.space),
                area=AreaDTO.model_validate(agenda_item.space.area),
                venue=VenueDTO.model_validate(agenda_item.space.area.venue),
            ),
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "current_hour_data": {},
                "ended_hour_data": {},
                "enrollment_requires_slots": False,
                "event": event,
                "filterable_tag_categories": [],
                "future_unavailable_hour_data": {
                    agenda_item.start_time: [session_data]
                },
                "hour_data": {agenda_item.start_time: [session_data]},
                "object": event,
                "sessions": [session_data],
                "user_enrollment_config": None,
                "total_enrolled": 0,
                "user_enrolled_sessions": [],
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )

    def test_ok_ended_session(self, active_user, agenda_item, client, event, faker):
        agenda_item.start_time = faker.date_time_between("-20d", "-10d", tzinfo=UTC)
        agenda_item.end_time = faker.date_time_between("-9d", "-1d", tzinfo=UTC)
        agenda_item.save()
        response = client.get(self._get_url(event.slug))

        session_data = SessionData(
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            full_participant_info="0/10",
            has_any_enrollments=False,
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=LocationData(
                space=SpaceDTO.model_validate(agenda_item.space),
                area=AreaDTO.model_validate(agenda_item.space.area),
                venue=VenueDTO.model_validate(agenda_item.space.area.venue),
            ),
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "current_hour_data": {},
                "ended_hour_data": {agenda_item.start_time: [session_data]},
                "enrollment_requires_slots": False,
                "event": event,
                "filterable_tag_categories": [],
                "future_unavailable_hour_data": {},
                "hour_data": {agenda_item.start_time: [session_data]},
                "object": event,
                "sessions": [session_data],
                "user_enrollment_config": None,
                "total_enrolled": 0,
                "user_enrolled_sessions": [],
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )

    def test_ok_current_session(self, active_user, agenda_item, client, event, faker):
        agenda_item.start_time = faker.date_time_between("-10d", "-1d", tzinfo=UTC)
        agenda_item.end_time = faker.date_time_between("+1d", "+10d", tzinfo=UTC)
        agenda_item.save()
        response = client.get(self._get_url(event.slug))

        session_data = SessionData(
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            full_participant_info="0/10",
            has_any_enrollments=False,
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=LocationData(
                space=SpaceDTO.model_validate(agenda_item.space),
                area=AreaDTO.model_validate(agenda_item.space.area),
                venue=VenueDTO.model_validate(agenda_item.space.area.venue),
            ),
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "current_hour_data": {agenda_item.start_time: [session_data]},
                "ended_hour_data": {},
                "enrollment_requires_slots": False,
                "event": event,
                "filterable_tag_categories": [],
                "future_unavailable_hour_data": {},
                "hour_data": {agenda_item.start_time: [session_data]},
                "object": event,
                "sessions": [session_data],
                "user_enrollment_config": None,
                "total_enrolled": 0,
                "user_enrolled_sessions": [],
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )

    def test_ok_reset_anonymous_enrollment(self, authenticated_client, event):
        session = authenticated_client.session
        session["anonymous_user_code"] = 123
        session["anonymous_enrollment_active"] = 123
        session["anonymous_event_id"] = 123
        session["anonymous_site_id"] = 123
        session.save()
        response = authenticated_client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "current_hour_data": {},
                "ended_hour_data": {},
                "enrollment_requires_slots": False,
                "event": event,
                "filterable_tag_categories": [],
                "future_unavailable_hour_data": {},
                "hour_data": {},
                "object": event,
                "pending_sessions": [],
                "sessions": [],
                "user_enrollment_config": None,
                "total_enrolled": 0,
                "user_enrolled_sessions": [],
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )
        assert not authenticated_client.session.get("anonymous_user_code")
        assert not authenticated_client.session.get("anonymous_enrollment_active")
        assert not authenticated_client.session.get("anonymous_event_id")
        assert not authenticated_client.session.get("anonymous_site_id")

    def test_ok_anonymous_enrollment_active(
        self, anonymous_user_factory, client, event, settings
    ):
        session = client.session
        user = anonymous_user_factory()
        session["anonymous_user_code"] = user.slug.split("_")[1]
        session["anonymous_enrollment_active"] = True
        session["anonymous_event_id"] = event.pk
        session["anonymous_site_id"] = event.sphere.site.pk
        session.save()
        client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key

        response = client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "anonymous_code": user.slug.split("_")[1],
                "anonymous_user_enrollments": [],
                "current_hour_data": {},
                "ended_hour_data": {},
                "enrollment_requires_slots": False,
                "event": event,
                "filterable_tag_categories": [],
                "future_unavailable_hour_data": {},
                "hour_data": {},
                "object": event,
                "sessions": [],
                "user_enrollment_config": None,
                "total_enrolled": 0,
                "user_enrolled_sessions": [],
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )

    def test_ok_anonymous_enrollment_active_no_user(self, client, event, settings):
        session = client.session
        session["anonymous_user_code"] = 17
        session["anonymous_enrollment_active"] = True
        session["anonymous_event_id"] = event.pk
        session["anonymous_site_id"] = event.sphere.site.pk
        session.save()
        client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key

        response = client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "current_hour_data": {},
                "ended_hour_data": {},
                "enrollment_requires_slots": False,
                "event": event,
                "filterable_tag_categories": [],
                "future_unavailable_hour_data": {},
                "hour_data": {},
                "object": event,
                "sessions": [],
                "user_enrollment_config": None,
                "total_enrolled": 0,
                "user_enrolled_sessions": [],
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )
        assert not client.session.get("anonymous_user_code")
        assert not client.session.get("anonymous_enrollment_active")
        assert not client.session.get("anonymous_event_id")
        assert not client.session.get("anonymous_site_id")

    def test_ok_anonymous_enrollment_active_wrong_site(self, client, event, settings):
        session = client.session
        session["anonymous_user_code"] = 17
        session["anonymous_enrollment_active"] = True
        session["anonymous_event_id"] = event.pk
        session["anonymous_site_id"] = "nosite"
        session.save()
        client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key

        response = client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "current_hour_data": {},
                "ended_hour_data": {},
                "enrollment_requires_slots": False,
                "event": event,
                "filterable_tag_categories": [],
                "future_unavailable_hour_data": {},
                "hour_data": {},
                "object": event,
                "sessions": [],
                "user_enrollment_config": None,
                "total_enrolled": 0,
                "user_enrolled_sessions": [],
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )
        assert not client.session.get("anonymous_user_code")
        assert not client.session.get("anonymous_enrollment_active")
        assert not client.session.get("anonymous_event_id")
        assert not client.session.get("anonymous_site_id")

    def test_ok_anonymous_enrollment_active_no_user_id(self, client, event, settings):
        session = client.session
        session["anonymous_enrollment_active"] = True
        session["anonymous_event_id"] = event.pk
        session["anonymous_site_id"] = "nosite"
        session.save()
        client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key

        response = client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "current_hour_data": {},
                "ended_hour_data": {},
                "enrollment_requires_slots": False,
                "event": event,
                "filterable_tag_categories": [],
                "future_unavailable_hour_data": {},
                "hour_data": {},
                "object": event,
                "sessions": [],
                "user_enrollment_config": None,
                "total_enrolled": 0,
                "user_enrolled_sessions": [],
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )
        assert not client.session.get("anonymous_user_code")
        assert not client.session.get("anonymous_enrollment_active")
        assert not client.session.get("anonymous_event_id")
        assert not client.session.get("anonymous_site_id")

    def test_ok_anonymous_enrollment_active_wrong_user_id(
        self, client, event, settings
    ):
        session = client.session
        session["anonymous_user_code"] = "notanid"
        session["anonymous_enrollment_active"] = True
        session["anonymous_event_id"] = event.pk
        session["anonymous_site_id"] = "nosite"
        session.save()
        client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key

        response = client.get(self._get_url(event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "current_hour_data": {},
                "ended_hour_data": {},
                "enrollment_requires_slots": False,
                "event": event,
                "filterable_tag_categories": [],
                "future_unavailable_hour_data": {},
                "hour_data": {},
                "object": event,
                "sessions": [],
                "user_enrollment_config": None,
                "total_enrolled": 0,
                "user_enrolled_sessions": [],
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )
        assert not client.session.get("anonymous_user_code")
        assert not client.session.get("anonymous_enrollment_active")
        assert not client.session.get("anonymous_event_id")
        assert not client.session.get("anonymous_site_id")

    def test_ok_anonymous_enrollment_with_participation(
        self, active_user, agenda_item, anonymous_user_factory, client, event, settings
    ):
        session = client.session
        user = anonymous_user_factory()
        participation = SessionParticipation.objects.create(
            user=user,
            session=agenda_item.session,
            status=SessionParticipationStatus.CONFIRMED,
        )
        session["anonymous_user_code"] = user.slug.split("_")[1]
        session["anonymous_enrollment_active"] = True
        session["anonymous_event_id"] = event.pk
        session["anonymous_site_id"] = event.sphere.site.pk
        session.save()
        client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key

        response = client.get(self._get_url(event.slug))

        session_data = SessionData(
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=1,
            full_participant_info="1/10",
            has_any_enrollments=True,
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[
                ParticipationInfo(
                    user=UserInfo.from_user_dto(
                        UserDTO.model_validate(participation.user),
                        gravatar_url=gravatar_url,
                    ),
                    status=participation.status,
                    creation_time=participation.creation_time,
                )
            ],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=LocationData(
                space=SpaceDTO.model_validate(agenda_item.space),
                area=AreaDTO.model_validate(agenda_item.space.area),
                venue=VenueDTO.model_validate(agenda_item.space.area.venue),
            ),
            user_enrolled=True,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "anonymous_code": user.slug.split("_")[1],
                "anonymous_user_enrollments": [participation],
                "current_hour_data": {},
                "ended_hour_data": {},
                "enrollment_requires_slots": False,
                "event": event,
                "filterable_tag_categories": [],
                "future_unavailable_hour_data": {
                    agenda_item.start_time: [session_data]
                },
                "hour_data": {agenda_item.start_time: [session_data]},
                "object": event,
                "sessions": [session_data],
                "user_enrollment_config": None,
                "total_enrolled": 1,
                "user_enrolled_sessions": [session_data],
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )

    def test_ok_current_session_enrollment_config_limit(
        self, active_user, agenda_item, client, enrollment_config, event, faker
    ):
        enrollment_config.limit_to_end_time = True
        enrollment_config.save()
        agenda_item.start_time = faker.date_time_between("-10d", "-1d", tzinfo=UTC)
        agenda_item.end_time = faker.date_time_between("+1d", "+10d", tzinfo=UTC)
        agenda_item.save()
        response = client.get(self._get_url(event.slug))

        session_data = SessionData(
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            full_participant_info="0/10",
            has_any_enrollments=False,
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=True,
            loc=LocationData(
                space=SpaceDTO.model_validate(agenda_item.space),
                area=AreaDTO.model_validate(agenda_item.space.area),
                venue=VenueDTO.model_validate(agenda_item.space.area.venue),
            ),
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "current_hour_data": {agenda_item.start_time: [session_data]},
                "ended_hour_data": {},
                "enrollment_requires_slots": False,
                "event": event,
                "filterable_tag_categories": [],
                "future_unavailable_hour_data": {},
                "hour_data": {agenda_item.start_time: [session_data]},
                "object": event,
                "sessions": [session_data],
                "user_enrollment_config": None,
                "total_enrolled": 0,
                "user_enrolled_sessions": [],
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )

    @pytest.mark.parametrize("fetched_from_api", (True, False))
    def test_ok_current_session_sum_time_slots(
        self,
        active_user,
        agenda_item,
        authenticated_client,
        enrollment_config,
        event,
        faker,
        fetched_from_api,
    ):
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        other_config = EnrollmentConfig.objects.create(
            event=event,
            start_time=faker.date_time_between("-3d", "-1d"),
            end_time=faker.date_time_between("+1d", "+3d"),
            percentage_slots=100,
            restrict_to_configured_users=True,
        )
        primary_slots = 7
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email=active_user.email,
            allowed_slots=primary_slots,
            fetched_from_api=fetched_from_api,
        )
        other_slots = 8
        UserEnrollmentConfig.objects.create(
            enrollment_config=other_config,
            user_email=active_user.email,
            allowed_slots=other_slots,
            fetched_from_api=fetched_from_api,
        )
        agenda_item.start_time = faker.date_time_between("-10d", "-1d", tzinfo=UTC)
        agenda_item.end_time = faker.date_time_between("+1d", "+10d", tzinfo=UTC)
        agenda_item.save()
        response = authenticated_client.get(self._get_url(event.slug))

        session_data = SessionData(
            can_edit=True,
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            full_participant_info="0/10",
            has_any_enrollments=False,
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=LocationData(
                space=SpaceDTO.model_validate(agenda_item.space),
                area=AreaDTO.model_validate(agenda_item.space.area),
                venue=VenueDTO.model_validate(agenda_item.space.area.venue),
            ),
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "current_hour_data": {agenda_item.start_time: [session_data]},
                "ended_hour_data": {},
                "enrollment_requires_slots": True,
                "event": event,
                "filterable_tag_categories": [],
                "future_unavailable_hour_data": {},
                "hour_data": {agenda_item.start_time: [session_data]},
                "object": event,
                "pending_sessions": [],
                "sessions": [session_data],
                "total_enrolled": 0,
                "user_enrolled_sessions": [],
                "user_enrollment_config": VirtualEnrollmentConfig(
                    allowed_slots=7 + 8, has_domain_config=False, has_user_config=True
                ),
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )

    @responses.activate
    def test_ok_current_session_get_user_config_from_api(
        self,
        active_user,
        agenda_item,
        authenticated_client,
        enrollment_config,
        event,
        faker,
        settings,
    ):
        slots = 7
        responses.get(
            url=settings.MEMBERSHIP_API_BASE_URL,
            status=HTTPStatus.OK,
            match=[
                responses.matchers.query_param_matcher({"email": active_user.email})
            ],
            json={"membership_count": slots},
        )
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        agenda_item.start_time = faker.date_time_between("-10d", "-1d", tzinfo=UTC)
        agenda_item.end_time = faker.date_time_between("+1d", "+10d", tzinfo=UTC)
        agenda_item.save()
        response = authenticated_client.get(self._get_url(event.slug))

        session_data = SessionData(
            can_edit=True,
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            full_participant_info="0/10",
            has_any_enrollments=False,
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=LocationData(
                space=SpaceDTO.model_validate(agenda_item.space),
                area=AreaDTO.model_validate(agenda_item.space.area),
                venue=VenueDTO.model_validate(agenda_item.space.area.venue),
            ),
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "current_hour_data": {agenda_item.start_time: [session_data]},
                "ended_hour_data": {},
                "enrollment_requires_slots": True,
                "event": event,
                "filterable_tag_categories": [],
                "future_unavailable_hour_data": {},
                "hour_data": {agenda_item.start_time: [session_data]},
                "object": event,
                "pending_sessions": [],
                "sessions": [session_data],
                "total_enrolled": 0,
                "user_enrolled_sessions": [],
                "user_enrollment_config": VirtualEnrollmentConfig(
                    allowed_slots=slots, has_domain_config=False, has_user_config=True
                ),
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )

    @responses.activate
    def test_ok_current_session_domain_config(
        self,
        active_user,
        agenda_item,
        authenticated_client,
        enrollment_config,
        event,
        faker,
        settings,
    ):
        responses.get(
            url=settings.MEMBERSHIP_API_BASE_URL,
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
            match=[
                responses.matchers.query_param_matcher({"email": active_user.email})
            ],
        )
        slots = 7
        DomainEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            domain=active_user.email.split("@")[1],
            allowed_slots_per_user=slots,
        )
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        agenda_item.start_time = faker.date_time_between("-10d", "-1d", tzinfo=UTC)
        agenda_item.end_time = faker.date_time_between("+1d", "+10d", tzinfo=UTC)
        agenda_item.save()
        response = authenticated_client.get(self._get_url(event.slug))

        session_data = SessionData(
            can_edit=True,
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            full_participant_info="0/10",
            has_any_enrollments=False,
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=LocationData(
                space=SpaceDTO.model_validate(agenda_item.space),
                area=AreaDTO.model_validate(agenda_item.space.area),
                venue=VenueDTO.model_validate(agenda_item.space.area.venue),
            ),
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "current_hour_data": {agenda_item.start_time: [session_data]},
                "ended_hour_data": {},
                "enrollment_requires_slots": True,
                "event": event,
                "filterable_tag_categories": [],
                "future_unavailable_hour_data": {},
                "hour_data": {agenda_item.start_time: [session_data]},
                "object": event,
                "pending_sessions": [],
                "sessions": [session_data],
                "total_enrolled": 0,
                "user_enrolled_sessions": [],
                "user_enrollment_config": VirtualEnrollmentConfig(
                    allowed_slots=slots, has_domain_config=True, has_user_config=False
                ),
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )

    def test_ok_current_session_domain_config_combined_with_user(
        self,
        active_user,
        agenda_item,
        authenticated_client,
        enrollment_config,
        event,
        faker,
    ):
        primary_slots = 8
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email=active_user.email,
            allowed_slots=primary_slots,
        )
        domain_slots = 7
        DomainEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            domain=active_user.email.split("@")[1],
            allowed_slots_per_user=domain_slots,
        )
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        agenda_item.start_time = faker.date_time_between("-10d", "-1d", tzinfo=UTC)
        agenda_item.end_time = faker.date_time_between("+1d", "+10d", tzinfo=UTC)
        agenda_item.save()
        response = authenticated_client.get(self._get_url(event.slug))

        session_data = SessionData(
            can_edit=True,
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            full_participant_info="0/10",
            has_any_enrollments=False,
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=LocationData(
                space=SpaceDTO.model_validate(agenda_item.space),
                area=AreaDTO.model_validate(agenda_item.space.area),
                venue=VenueDTO.model_validate(agenda_item.space.area.venue),
            ),
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "current_hour_data": {agenda_item.start_time: [session_data]},
                "ended_hour_data": {},
                "enrollment_requires_slots": True,
                "event": event,
                "filterable_tag_categories": [],
                "future_unavailable_hour_data": {},
                "hour_data": {agenda_item.start_time: [session_data]},
                "object": event,
                "pending_sessions": [],
                "sessions": [session_data],
                "total_enrolled": 0,
                "user_enrolled_sessions": [],
                "user_enrollment_config": VirtualEnrollmentConfig(
                    allowed_slots=primary_slots + domain_slots,
                    has_domain_config=True,
                    has_user_config=True,
                ),
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )

    @responses.activate
    def test_ok_current_session_get_user_config_from_api_http_error(
        self,
        active_user,
        agenda_item,
        authenticated_client,
        enrollment_config,
        event,
        faker,
        settings,
    ):
        settings.MEMBERSHIP_API_BASE_URL = "https://api.example.com/check/member"
        settings.MEMBERSHIP_API_TOKEN = faker.uuid4()
        responses.get(
            url=settings.MEMBERSHIP_API_BASE_URL,
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
            match=[
                responses.matchers.query_param_matcher({"email": active_user.email})
            ],
            json={"membership_count": 7},
        )
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        agenda_item.start_time = faker.date_time_between("-10d", "-1d", tzinfo=UTC)
        agenda_item.end_time = faker.date_time_between("+1d", "+10d", tzinfo=UTC)
        agenda_item.save()
        response = authenticated_client.get(self._get_url(event.slug))

        session_data = SessionData(
            can_edit=True,
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            full_participant_info="0/10",
            has_any_enrollments=False,
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=LocationData(
                space=SpaceDTO.model_validate(agenda_item.space),
                area=AreaDTO.model_validate(agenda_item.space.area),
                venue=VenueDTO.model_validate(agenda_item.space.area.venue),
            ),
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "current_hour_data": {agenda_item.start_time: [session_data]},
                "ended_hour_data": {},
                "enrollment_requires_slots": True,
                "event": event,
                "filterable_tag_categories": [],
                "future_unavailable_hour_data": {},
                "hour_data": {agenda_item.start_time: [session_data]},
                "object": event,
                "pending_sessions": [],
                "sessions": [session_data],
                "user_enrollment_config": None,
                "total_enrolled": 0,
                "user_enrolled_sessions": [],
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )

    @responses.activate
    def test_ok_current_session_get_user_config_from_api_json_error(
        self,
        active_user,
        agenda_item,
        authenticated_client,
        enrollment_config,
        event,
        faker,
        settings,
    ):
        settings.MEMBERSHIP_API_BASE_URL = "https://api.example.com/check/member"
        settings.MEMBERSHIP_API_TOKEN = faker.uuid4()
        responses.get(
            url=settings.MEMBERSHIP_API_BASE_URL,
            status=HTTPStatus.OK,
            match=[
                responses.matchers.query_param_matcher({"email": active_user.email})
            ],
            json=["a"],
        )
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        agenda_item.start_time = faker.date_time_between("-10d", "-1d", tzinfo=UTC)
        agenda_item.end_time = faker.date_time_between("+1d", "+10d", tzinfo=UTC)
        agenda_item.save()
        response = authenticated_client.get(self._get_url(event.slug))

        session_data = SessionData(
            can_edit=True,
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            full_participant_info="0/10",
            has_any_enrollments=False,
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=LocationData(
                space=SpaceDTO.model_validate(agenda_item.space),
                area=AreaDTO.model_validate(agenda_item.space.area),
                venue=VenueDTO.model_validate(agenda_item.space.area.venue),
            ),
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "current_hour_data": {agenda_item.start_time: [session_data]},
                "ended_hour_data": {},
                "enrollment_requires_slots": True,
                "event": event,
                "filterable_tag_categories": [],
                "future_unavailable_hour_data": {},
                "hour_data": {agenda_item.start_time: [session_data]},
                "object": event,
                "pending_sessions": [],
                "sessions": [session_data],
                "user_enrollment_config": None,
                "total_enrolled": 0,
                "user_enrolled_sessions": [],
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )

    @responses.activate
    def test_ok_current_session_get_user_config_from_api_refetch(
        self,
        active_user,
        agenda_item,
        authenticated_client,
        enrollment_config,
        event,
        faker,
        settings,
    ):
        settings.MEMBERSHIP_API_BASE_URL = "https://api.example.com/check/member"
        settings.MEMBERSHIP_API_TOKEN = faker.uuid4()
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email=active_user.email,
            allowed_slots=0,
            last_check=faker.date_time_between("-10d", "-5d"),
        )
        slots = 7
        responses.get(
            url=settings.MEMBERSHIP_API_BASE_URL,
            status=HTTPStatus.OK,
            match=[
                responses.matchers.query_param_matcher({"email": active_user.email})
            ],
            json={"membership_count": slots},
        )
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        agenda_item.start_time = faker.date_time_between("-10d", "-1d", tzinfo=UTC)
        agenda_item.end_time = faker.date_time_between("+1d", "+10d", tzinfo=UTC)
        agenda_item.save()
        response = authenticated_client.get(self._get_url(event.slug))

        assert UserEnrollmentConfig.objects.get(
            enrollment_config=enrollment_config,
            user_email=active_user.email,
            allowed_slots=slots,
        )
        session_data = SessionData(
            can_edit=True,
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            full_participant_info="0/10",
            has_any_enrollments=False,
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=LocationData(
                space=SpaceDTO.model_validate(agenda_item.space),
                area=AreaDTO.model_validate(agenda_item.space.area),
                venue=VenueDTO.model_validate(agenda_item.space.area.venue),
            ),
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "current_hour_data": {agenda_item.start_time: [session_data]},
                "ended_hour_data": {},
                "enrollment_requires_slots": True,
                "event": event,
                "filterable_tag_categories": [],
                "future_unavailable_hour_data": {},
                "hour_data": {agenda_item.start_time: [session_data]},
                "object": event,
                "pending_sessions": [],
                "sessions": [session_data],
                "total_enrolled": 0,
                "user_enrolled_sessions": [],
                "user_enrollment_config": VirtualEnrollmentConfig(
                    allowed_slots=slots, has_domain_config=False, has_user_config=True
                ),
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )

    def test_ok_current_session_get_user_config_from_api_no_refetch(
        self,
        active_user,
        agenda_item,
        authenticated_client,
        enrollment_config,
        event,
        faker,
        settings,
    ):
        settings.MEMBERSHIP_API_BASE_URL = "https://api.example.com/check/member"
        settings.MEMBERSHIP_API_TOKEN = faker.uuid4()
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email=active_user.email,
            allowed_slots=0,
            last_check=faker.date_time_between("-1m", "now"),
        )
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        agenda_item.start_time = faker.date_time_between("-10d", "-1d", tzinfo=UTC)
        agenda_item.end_time = faker.date_time_between("+1d", "+10d", tzinfo=UTC)
        agenda_item.save()
        response = authenticated_client.get(self._get_url(event.slug))

        assert UserEnrollmentConfig.objects.get(
            enrollment_config=enrollment_config,
            user_email=active_user.email,
            allowed_slots=0,
        )
        session_data = SessionData(
            can_edit=True,
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            full_participant_info="0/10",
            has_any_enrollments=False,
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=LocationData(
                space=SpaceDTO.model_validate(agenda_item.space),
                area=AreaDTO.model_validate(agenda_item.space.area),
                venue=VenueDTO.model_validate(agenda_item.space.area.venue),
            ),
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "current_hour_data": {agenda_item.start_time: [session_data]},
                "ended_hour_data": {},
                "enrollment_requires_slots": True,
                "event": event,
                "filterable_tag_categories": [],
                "future_unavailable_hour_data": {},
                "hour_data": {agenda_item.start_time: [session_data]},
                "object": event,
                "pending_sessions": [],
                "sessions": [session_data],
                "user_enrollment_config": VirtualEnrollmentConfig(
                    allowed_slots=0, has_domain_config=False, has_user_config=True
                ),
                "total_enrolled": 0,
                "user_enrolled_sessions": [],
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )

    @responses.activate
    def test_ok_current_session_get_user_config_from_api_refetch_zero(
        self,
        active_user,
        agenda_item,
        authenticated_client,
        enrollment_config,
        event,
        faker,
        settings,
    ):
        settings.MEMBERSHIP_API_BASE_URL = "https://api.example.com/check/member"
        settings.MEMBERSHIP_API_TOKEN = faker.uuid4()
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email=active_user.email,
            allowed_slots=0,
            last_check=faker.date_time_between("-10d", "-5d"),
        )
        responses.get(
            url=settings.MEMBERSHIP_API_BASE_URL,
            status=HTTPStatus.OK,
            match=[
                responses.matchers.query_param_matcher({"email": active_user.email})
            ],
            json={"membership_count": 0},
        )
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        agenda_item.start_time = faker.date_time_between("-10d", "-1d", tzinfo=UTC)
        agenda_item.end_time = faker.date_time_between("+1d", "+10d", tzinfo=UTC)
        agenda_item.save()
        response = authenticated_client.get(self._get_url(event.slug))

        assert UserEnrollmentConfig.objects.get(
            enrollment_config=enrollment_config,
            user_email=active_user.email,
            allowed_slots=0,
        )
        session_data = SessionData(
            can_edit=True,
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            full_participant_info="0/10",
            has_any_enrollments=False,
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=LocationData(
                space=SpaceDTO.model_validate(agenda_item.space),
                area=AreaDTO.model_validate(agenda_item.space.area),
                venue=VenueDTO.model_validate(agenda_item.space.area.venue),
            ),
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "current_hour_data": {agenda_item.start_time: [session_data]},
                "ended_hour_data": {},
                "enrollment_requires_slots": True,
                "event": event,
                "filterable_tag_categories": [],
                "future_unavailable_hour_data": {},
                "hour_data": {agenda_item.start_time: [session_data]},
                "object": event,
                "pending_sessions": [],
                "sessions": [session_data],
                "total_enrolled": 0,
                "user_enrolled_sessions": [],
                "user_enrollment_config": VirtualEnrollmentConfig(
                    allowed_slots=0, has_domain_config=False, has_user_config=True
                ),
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )

    @responses.activate
    def test_ok_current_session_get_user_config_from_api_zero(
        self,
        active_user,
        agenda_item,
        authenticated_client,
        enrollment_config,
        event,
        faker,
        settings,
    ):
        settings.MEMBERSHIP_API_BASE_URL = "https://api.example.com/check/member"
        settings.MEMBERSHIP_API_TOKEN = faker.uuid4()
        responses.get(
            url=settings.MEMBERSHIP_API_BASE_URL,
            status=HTTPStatus.OK,
            match=[
                responses.matchers.query_param_matcher({"email": active_user.email})
            ],
            json={"membership_count": 0},
        )
        enrollment_config.restrict_to_configured_users = True
        enrollment_config.save()
        agenda_item.start_time = faker.date_time_between("-10d", "-1d", tzinfo=UTC)
        agenda_item.end_time = faker.date_time_between("+1d", "+10d", tzinfo=UTC)
        agenda_item.save()
        response = authenticated_client.get(self._get_url(event.slug))

        assert UserEnrollmentConfig.objects.get(
            enrollment_config=enrollment_config,
            user_email=active_user.email,
            allowed_slots=0,
        )
        session_data = SessionData(
            can_edit=True,
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            full_participant_info="0/10",
            has_any_enrollments=False,
            is_enrollment_available=True,
            is_full=False,
            is_ongoing=True,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(agenda_item.session),
            should_show_as_inactive=False,
            loc=LocationData(
                space=SpaceDTO.model_validate(agenda_item.space),
                area=AreaDTO.model_validate(agenda_item.space.area),
                venue=VenueDTO.model_validate(agenda_item.space.area.venue),
            ),
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "current_hour_data": {agenda_item.start_time: [session_data]},
                "ended_hour_data": {},
                "enrollment_requires_slots": True,
                "event": event,
                "filterable_tag_categories": [],
                "future_unavailable_hour_data": {},
                "hour_data": {agenda_item.start_time: [session_data]},
                "object": event,
                "pending_sessions": [],
                "sessions": [session_data],
                "total_enrolled": 0,
                "user_enrolled_sessions": [],
                "user_enrollment_config": VirtualEnrollmentConfig(
                    allowed_slots=0, has_domain_config=False, has_user_config=True
                ),
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )

    def test_ok_session_with_displayed_field_values(
        self, active_user, agenda_item, client, event
    ):
        """Select field values are shown on cards when the field is displayed."""
        session_field = SessionField.objects.create(
            event=event,
            name="Game Type",
            question="Game Type",
            slug="game-type",
            field_type="select",
            is_multiple=True,
            is_public=True,
            icon="puzzle-piece",
        )
        session = agenda_item.session
        SessionFieldValue.objects.create(
            session=session, field=session_field, value=["RPG"]
        )
        settings, _ = EventSettings.objects.get_or_create(event=event)
        settings.displayed_session_fields.add(session_field)

        response = client.get(self._get_url(event.slug))

        field_value_dto = SessionFieldValueDTO(
            allow_custom=False,
            field_icon="puzzle-piece",
            field_id=session_field.pk,
            field_name="Game Type",
            field_question="Game Type",
            field_slug="game-type",
            field_type="select",
            is_public=True,
            value=["RPG"],
        )
        session_data = SessionData(
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            displayed_field_rows=[build_display_field_row(field_value_dto)],
            full_participant_info="0/10",
            has_any_enrollments=False,
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(session),
            should_show_as_inactive=False,
            loc=LocationData(
                space=SpaceDTO.model_validate(agenda_item.space),
                area=AreaDTO.model_validate(agenda_item.space.area),
                venue=VenueDTO.model_validate(agenda_item.space.area.venue),
            ),
            field_values=[field_value_dto],
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "current_hour_data": {},
                "ended_hour_data": {},
                "enrollment_requires_slots": False,
                "event": event,
                "filterable_tag_categories": [session_field],
                "future_unavailable_hour_data": {
                    agenda_item.start_time: [session_data]
                },
                "hour_data": {agenda_item.start_time: [session_data]},
                "object": event,
                "sessions": [session_data],
                "user_enrollment_config": None,
                "total_enrolled": 0,
                "user_enrolled_sessions": [],
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )

    def test_ok_session_with_non_displayed_field_excluded_from_rows(
        self, active_user, agenda_item, client, event
    ):
        """Field values not in displayed_session_fields are excluded from rows."""
        session_field = SessionField.objects.create(
            event=event,
            name="RPG System",
            question="What RPG system?",
            slug="rpg-system",
            field_type="text",
            is_public=True,
        )
        session = agenda_item.session
        SessionFieldValue.objects.create(
            session=session, field=session_field, value="D&D 5e"
        )

        response = client.get(self._get_url(event.slug))

        session_data = SessionData(
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            full_participant_info="0/10",
            has_any_enrollments=False,
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(session),
            should_show_as_inactive=False,
            loc=LocationData(
                space=SpaceDTO.model_validate(agenda_item.space),
                area=AreaDTO.model_validate(agenda_item.space.area),
                venue=VenueDTO.model_validate(agenda_item.space.area.venue),
            ),
            field_values=[
                SessionFieldValueDTO(
                    allow_custom=False,
                    field_icon="",
                    field_id=session_field.pk,
                    field_name="RPG System",
                    field_question="What RPG system?",
                    field_slug="rpg-system",
                    field_type="text",
                    is_public=True,
                    value="D&D 5e",
                )
            ],
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "current_hour_data": {},
                "ended_hour_data": {},
                "enrollment_requires_slots": False,
                "event": event,
                "filterable_tag_categories": [],
                "future_unavailable_hour_data": {
                    agenda_item.start_time: [session_data]
                },
                "hour_data": {agenda_item.start_time: [session_data]},
                "object": event,
                "sessions": [session_data],
                "user_enrollment_config": None,
                "total_enrolled": 0,
                "user_enrolled_sessions": [],
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )

    def test_ok_session_with_displayed_text_field(
        self, active_user, agenda_item, client, event
    ):
        """Text field values appear on cards when field is displayed."""
        session_field = SessionField.objects.create(
            event=event,
            name="RPG System",
            question="What RPG system?",
            slug="rpg-system",
            field_type="text",
            is_public=True,
        )
        session = agenda_item.session
        SessionFieldValue.objects.create(
            session=session, field=session_field, value="D&D 5e"
        )
        settings, _ = EventSettings.objects.get_or_create(event=event)
        settings.displayed_session_fields.add(session_field)

        response = client.get(self._get_url(event.slug))

        field_value_dto = SessionFieldValueDTO(
            allow_custom=False,
            field_icon="",
            field_id=session_field.pk,
            field_name="RPG System",
            field_question="What RPG system?",
            field_slug="rpg-system",
            field_type="text",
            is_public=True,
            value="D&D 5e",
        )
        session_data = SessionData(
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            displayed_field_rows=[build_display_field_row(field_value_dto)],
            full_participant_info="0/10",
            has_any_enrollments=False,
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(session),
            should_show_as_inactive=False,
            loc=LocationData(
                space=SpaceDTO.model_validate(agenda_item.space),
                area=AreaDTO.model_validate(agenda_item.space.area),
                venue=VenueDTO.model_validate(agenda_item.space.area.venue),
            ),
            field_values=[field_value_dto],
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "current_hour_data": {},
                "ended_hour_data": {},
                "enrollment_requires_slots": False,
                "event": event,
                "filterable_tag_categories": [],
                "future_unavailable_hour_data": {
                    agenda_item.start_time: [session_data]
                },
                "hour_data": {agenda_item.start_time: [session_data]},
                "object": event,
                "sessions": [session_data],
                "user_enrollment_config": None,
                "total_enrolled": 0,
                "user_enrolled_sessions": [],
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )

    def test_ok_session_with_displayed_checkbox_field(
        self, active_user, agenda_item, client, event
    ):
        """Checkbox field values appear on cards when field is displayed."""
        session_field = SessionField.objects.create(
            event=event,
            name="Beginner Friendly",
            question="Is this beginner friendly?",
            slug="beginner-friendly",
            field_type="checkbox",
            is_public=True,
            icon="academic-cap",
        )
        session = agenda_item.session
        SessionFieldValue.objects.create(
            session=session, field=session_field, value=True
        )
        settings, _ = EventSettings.objects.get_or_create(event=event)
        settings.displayed_session_fields.add(session_field)

        response = client.get(self._get_url(event.slug))

        field_value_dto = SessionFieldValueDTO(
            allow_custom=False,
            field_icon="academic-cap",
            field_id=session_field.pk,
            field_name="Beginner Friendly",
            field_question="Is this beginner friendly?",
            field_slug="beginner-friendly",
            field_type="checkbox",
            is_public=True,
            value=True,
        )
        session_data = SessionData(
            agenda_item=AgendaItemDTO.model_validate(agenda_item),
            effective_participants_limit=10,
            enrolled_count=0,
            displayed_field_rows=[build_display_field_row(field_value_dto)],
            full_participant_info="0/10",
            has_any_enrollments=False,
            is_enrollment_available=False,
            is_full=False,
            is_ongoing=False,
            presenter=UserInfo.from_user_dto(
                UserDTO.model_validate(active_user), gravatar_url=gravatar_url
            ),
            session_participations=[],
            session=SessionDTO.model_validate(session),
            should_show_as_inactive=False,
            loc=LocationData(
                space=SpaceDTO.model_validate(agenda_item.space),
                area=AreaDTO.model_validate(agenda_item.space.area),
                venue=VenueDTO.model_validate(agenda_item.space.area.venue),
            ),
            field_values=[field_value_dto],
            user_enrolled=False,
            user_waiting=False,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "current_hour_data": {},
                "ended_hour_data": {},
                "enrollment_requires_slots": False,
                "event": event,
                "filterable_tag_categories": [],
                "future_unavailable_hour_data": {
                    agenda_item.start_time: [session_data]
                },
                "hour_data": {agenda_item.start_time: [session_data]},
                "object": event,
                "sessions": [session_data],
                "user_enrollment_config": None,
                "total_enrolled": 0,
                "user_enrolled_sessions": [],
                "view": ANY,
            },
            template_name=["chronology/event.html"],
        )

    # Unpublished events are not 404s but redirects to the sphere home: the 404
    # fallback routes missing and unpublished events identically so a response
    # never reveals whether an unannounced event exists. See
    # TestSemantic404Recovery in tests/integration/web/test_error_views.py.
    def test_unpublished_event_redirects_anonymous_to_home(self, client, sphere):
        event = EventFactory(sphere=sphere, publication_time=None)

        response = client.get(self._get_url(event.slug))

        assert_response(response, HTTPStatus.FOUND, url=reverse("web:index"))

    def test_unpublished_event_redirects_regular_user_to_home(
        self, authenticated_client, sphere
    ):
        event = EventFactory(sphere=sphere, publication_time=None)

        response = authenticated_client.get(self._get_url(event.slug))

        assert_response(response, HTTPStatus.FOUND, url=reverse("web:index"))

    def test_unpublished_event_visible_for_manager(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        event = EventFactory(sphere=sphere, publication_time=None)

        response = authenticated_client.get(self._get_url(event.slug))

        assert response.status_code == HTTPStatus.OK


class TestEventPageEditAffordance:
    URL_NAME = "web:chronology:event"

    def _get_url(self, slug):
        return reverse(self.URL_NAME, kwargs={"slug": slug})

    def _scheduled_session(self, event, sphere, presenter):
        category = ProposalCategoryFactory(event=event)
        return SessionFactory(
            category=category,
            presenter=presenter,
            display_name=presenter.name,
            sphere=sphere,
            participants_limit=10,
            min_age=0,
            status="scheduled",
        )

    def test_owner_sees_edit_affordance(
        self, authenticated_client, event, sphere, active_user, space
    ):
        session = self._scheduled_session(event, sphere, active_user)
        AgendaItemFactory(session=session, space=space)
        edit_url = reverse(
            "web:chronology:session-edit",
            kwargs={"event_slug": event.slug, "session_id": session.pk},
        )

        response = authenticated_client.get(self._get_url(event.slug))

        session_data = next(
            s for s in response.context["sessions"] if s.session.pk == session.pk
        )
        assert session_data.can_edit is True
        content = response.content.decode()
        assert edit_url in content
        assert f'data-edit-open="{session.pk}"' in content

    def test_non_owner_no_edit_affordance(
        self, authenticated_client, event, sphere, space
    ):
        other = UserFactory(username="other", email="other@example.com")
        session = self._scheduled_session(event, sphere, other)
        AgendaItemFactory(session=session, space=space)
        edit_url = reverse(
            "web:chronology:session-edit",
            kwargs={"event_slug": event.slug, "session_id": session.pk},
        )

        response = authenticated_client.get(self._get_url(event.slug))

        session_data = next(
            s for s in response.context["sessions"] if s.session.pk == session.pk
        )
        assert session_data.can_edit is False
        content = response.content.decode()
        assert edit_url not in content
        assert f'data-edit-open="{session.pk}"' not in content

    def test_owner_no_affordance_when_opted_out(
        self, authenticated_client, event, sphere, active_user, space
    ):
        event.allow_facilitator_session_edit = False
        event.save()
        session = self._scheduled_session(event, sphere, active_user)
        AgendaItemFactory(session=session, space=space)
        edit_url = reverse(
            "web:chronology:session-edit",
            kwargs={"event_slug": event.slug, "session_id": session.pk},
        )

        response = authenticated_client.get(self._get_url(event.slug))

        session_data = next(
            s for s in response.context["sessions"] if s.session.pk == session.pk
        )
        assert session_data.can_edit is False
        content = response.content.decode()
        assert edit_url not in content
        assert f'data-edit-open="{session.pk}"' not in content
