from datetime import UTC, datetime
from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import EnrollmentConfig
from ludamus.pacts.enrollment import EnrollmentWindowDTO
from tests.integration.conftest import EventFactory, SphereFactory
from tests.integration.utils import (
    FormErrorsMatcher,
    RequestTimeMatcher,
    assert_login_required,
    assert_response,
)
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_not_a_manager,
    panel_context,
    settings_tab_urls,
)

EARLY_CAPACITY_PERCENT = 50
FULL_CAPACITY_PERCENT = 100
MAX_WAITLIST_SESSIONS = 3
WINDOW_COUNT = 2


def _list_url(event):
    return reverse("panel:event-enrollment-settings", kwargs={"slug": event.slug})


def _create_url(event):
    return reverse("panel:enrollment-window-create", kwargs={"slug": event.slug})


def _edit_url(event, window):
    return reverse(
        "panel:enrollment-window-edit", kwargs={"slug": event.slug, "pk": window.pk}
    )


def _delete_url(event, window):
    return reverse(
        "panel:enrollment-window-delete", kwargs={"slug": event.slug, "pk": window.pk}
    )


def _post_data(**overrides):
    data = {
        "start_time": "2026-08-01T10:00",
        "end_time": "2026-08-20T18:00",
        "percentage_slots": str(FULL_CAPACITY_PERCENT),
        "max_waitlist_sessions": str(MAX_WAITLIST_SESSIONS),
        "banner_text": "Enrollment is open",
    }
    data.update(overrides)
    return data


def _settings_context(event, *, windows):
    return {
        **panel_context(event, active_nav="settings"),
        "active_tab": "enrollment",
        "tab_urls": settings_tab_urls(event),
        "windows": windows,
        "now": RequestTimeMatcher(),
    }


def _window(event, **overrides):
    data = {
        "event": event,
        "start_time": datetime(2026, 8, 1, 10, tzinfo=UTC),
        "end_time": datetime(2026, 8, 20, 18, tzinfo=UTC),
    }
    data.update(overrides)
    return EnrollmentConfig.objects.create(**data)


class TestEventEnrollmentSettingsAccess:
    def test_redirects_anonymous_user_to_login(self, client, event):
        url = _list_url(event)

        response = client.get(url)

        assert_login_required(response, url)

    def test_redirects_non_manager(self, authenticated_client, event):
        response = authenticated_client.get(_list_url(event))

        assert_not_a_manager(response)

    def test_manager_cannot_access_another_spheres_event(self, panel_client, event):
        other_event = EventFactory(sphere=SphereFactory())

        response = panel_client.get(_list_url(other_event))

        assert_event_not_found(response)

    def test_manager_cannot_delete_another_spheres_window(self, panel_client, event):
        other_event = EventFactory(sphere=SphereFactory())
        other_window = _window(other_event)

        response = panel_client.post(_delete_url(other_event, other_window))

        assert_event_not_found(response)
        assert EnrollmentConfig.objects.filter(pk=other_window.pk).exists()


class TestEventEnrollmentSettingsList:
    def test_shows_empty_state_for_manager(self, panel_client, event):
        response = panel_client.get(_list_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/enrollment-settings.html",
            context_data=_settings_context(event, windows=[]),
            contains=["Enrollment is closed", "Add enrollment window"],
        )

    def test_lists_all_event_windows(self, panel_client, event):
        early = _window(
            event, banner_text="Early access", percentage_slots=EARLY_CAPACITY_PERCENT
        )
        general = _window(
            event,
            start_time=datetime(2026, 8, 21, 10, tzinfo=UTC),
            end_time=datetime(2026, 8, 25, 18, tzinfo=UTC),
            banner_text="General access",
        )

        response = panel_client.get(_list_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/enrollment-settings.html",
            context_data=_settings_context(
                event,
                windows=[
                    EnrollmentWindowDTO.model_validate(early),
                    EnrollmentWindowDTO.model_validate(general),
                ],
            ),
        )
        content = response.content.decode()
        assert "50% of capacity" in content
        assert "100% of capacity" in content
        assert content.count("Edit window") == WINDOW_COUNT


class TestEnrollmentWindowCreate:
    def test_creates_window_for_manager(self, panel_client, event):
        response = panel_client.post(
            _create_url(event),
            data=_post_data(
                limit_to_end_time="on",
                restrict_to_configured_users="on",
                allow_anonymous_enrollment="on",
            ),
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Enrollment window created.")],
            url=_list_url(event),
        )
        window = EnrollmentConfig.objects.get(event=event)
        assert window.percentage_slots == FULL_CAPACITY_PERCENT
        assert window.max_waitlist_sessions == MAX_WAITLIST_SESSIONS
        assert window.limit_to_end_time is True
        assert window.restrict_to_configured_users is True
        assert window.allow_anonymous_enrollment is True

    def test_re_renders_invalid_period_with_input(self, panel_client, event):
        response = panel_client.post(
            _create_url(event),
            data=_post_data(start_time="2026-08-20T18:00", end_time="2026-08-01T10:00"),
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/enrollment-window-form.html",
            context_data={
                **panel_context(event, active_nav="settings"),
                "active_tab": "enrollment",
                "tab_urls": settings_tab_urls(event),
                "form": FormErrorsMatcher(
                    __all__=["Enrollment must close after it opens."]
                ),
                "window": None,
            },
            contains="2026-08-20T18:00",
        )
        assert not EnrollmentConfig.objects.filter(event=event).exists()


class TestEnrollmentWindowEditAndDelete:
    def test_updates_window_for_manager(self, panel_client, event):
        window = _window(event)

        response = panel_client.post(
            _edit_url(event, window),
            data=_post_data(percentage_slots=str(EARLY_CAPACITY_PERCENT)),
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Enrollment window saved.")],
            url=_list_url(event),
        )
        window.refresh_from_db()
        assert window.percentage_slots == EARLY_CAPACITY_PERCENT

    def test_cannot_edit_window_from_another_event(self, panel_client, sphere, event):
        other_window = _window(EventFactory(sphere=sphere))

        response = panel_client.post(
            reverse(
                "panel:enrollment-window-edit",
                kwargs={"slug": event.slug, "pk": other_window.pk},
            ),
            data=_post_data(),
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Enrollment window not found.")],
            url=_list_url(event),
        )
        other_window.refresh_from_db()
        assert other_window.percentage_slots == FULL_CAPACITY_PERCENT

    def test_deletes_window_for_manager(self, panel_client, event):
        window = _window(event)

        response = panel_client.post(_delete_url(event, window))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Enrollment window deleted.")],
            url=_list_url(event),
        )
        assert not EnrollmentConfig.objects.filter(pk=window.pk).exists()
