from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.test import Client
from django.urls import reverse

from ludamus.links.db.django.models import ContentReport, Notification
from ludamus.pacts.legacy import NotificationKind
from ludamus.pacts.report import ReportedContentKind, ReportReason, ReportTargetDTO
from ludamus.specs.report import REPORTS_PER_WINDOW
from tests.integration.conftest import EventFactory, SessionFactory, UserFactory
from tests.integration.utils import (
    FormErrorsMatcher,
    assert_response,
    assert_response_404,
)

RECEIPT_SUBJECT = "We received your report #{}"
KIND_LABELS = {
    ReportedContentKind.SESSION: "session",
    ReportedContentKind.USER: "user profile",
}
NAME_REQUIRED = (
    "Enter your name. Only reports of child sexual abuse material can be sent "
    "without it."
)
EMAIL_REQUIRED = "Enter your email, so we can send you the receipt and our decision."
RATE_LIMITED = (
    "You have sent several reports in the last hour. Try again later, or write "
    "to support@example.com."
)


def _url(kind, object_id, origin=""):
    url = reverse("report", kwargs={"kind": kind, "object_id": object_id})
    return f"{url}?from={origin}" if origin else url


def _session_location(session):
    path = reverse("web:chronology:event", kwargs={"slug": session.event.slug})
    return f"https://testserver{path}?session={session.pk}"


def _post_data(**overrides):
    return {
        "reason": ReportReason.HATE_SPEECH.value,
        "explanation": "The description calls for violence against a group.",
        "reporter_name": "Rita Reporter",
        "reporter_email": "rita@example.com",
        "good_faith": "on",
        "from": "",
        **overrides,
    }


def _form_context(target, *, origin=""):
    return {
        "target": target,
        "kind_label": KIND_LABELS[target.kind],
        "form": ANY,
        "origin": origin,
        "back_url": origin or target.location,
    }


class TestReportPageView:
    def test_a_signed_out_visitor_gets_the_form_for_a_public_session(
        self, client, session
    ):
        origin = f"/event/{session.event.slug}/"

        response = client.get(_url("session", session.pk, origin))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="report/form.html",
            context_data=_form_context(
                ReportTargetDTO(
                    kind=ReportedContentKind.SESSION,
                    object_id=session.pk,
                    label=session.title,
                    location=_session_location(session),
                ),
                origin=origin,
            ),
        )

    def test_a_presenter_can_be_reported(self, client, session, active_user):
        response = client.get(_url("user", active_user.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="report/form.html",
            context_data=_form_context(
                ReportTargetDTO(
                    kind=ReportedContentKind.USER,
                    object_id=active_user.pk,
                    label="Test User",
                    location="https://testserver/",
                )
            ),
        )

    def test_an_offsite_from_is_dropped(self, client, session):
        response = client.get(_url("session", session.pk, "//evil.example/"))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="report/form.html",
            context_data=_form_context(
                ReportTargetDTO(
                    kind=ReportedContentKind.SESSION,
                    object_id=session.pk,
                    label=session.title,
                    location=_session_location(session),
                )
            ),
        )

    def test_unknown_kind_is_not_found(self, client, session):
        response = client.get(_url("listing", session.pk))

        assert_response_404(response)

    def test_a_session_of_an_unpublished_event_is_not_found(self, client, sphere):
        hidden = SessionFactory(
            event=EventFactory(
                sphere=sphere, publication_time=datetime.now(UTC) + timedelta(days=1)
            ),
            category=None,
        )

        response = client.get(_url("session", hidden.pk))

        assert_response_404(response)

    def test_another_spheres_session_is_not_found(self, client, non_root_sphere):
        foreign = SessionFactory(
            event=EventFactory(sphere=non_root_sphere), category=None
        )

        response = client.get(_url("session", foreign.pk))

        assert_response_404(response)

    def test_a_user_who_presents_nothing_here_is_not_found(self, client):
        stranger = UserFactory()

        response = client.get(_url("user", stranger.pk))

        assert_response_404(response)


class TestReportSubmit:
    def test_a_signed_out_report_is_stored_and_receipted(
        self, client, session, mailoutbox, django_capture_on_commit_callbacks
    ):
        origin = f"/event/{session.event.slug}/?session={session.pk}"

        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(
                _url("session", session.pk), _post_data(**{"from": origin})
            )

        report = ContentReport.objects.get()
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=origin,
            messages=[(messages.SUCCESS, "Report sent. We emailed you a receipt.")],
        )
        assert (
            report.object_id,
            report.content_label,
            report.location,
            report.reason,
            report.reporter_id,
            report.reporter_name,
            report.reporter_email,
            report.status,
            report.decided_automatically,
        ) == (
            session.pk,
            session.title,
            f"http://testserver{origin}",
            ReportReason.HATE_SPEECH,
            None,
            "Rita Reporter",
            "rita@example.com",
            "open",
            False,
        )
        assert [(mail.to, mail.subject) for mail in mailoutbox] == [
            (["rita@example.com"], RECEIPT_SUBJECT.format(report.pk))
        ]
        assert not Notification.objects.exists()

    def test_a_signed_in_reporter_also_gets_a_bell_notification(
        self,
        authenticated_client,
        active_user,
        event,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        reported = SessionFactory(event=event, category=None)

        with django_capture_on_commit_callbacks(execute=True):
            response = authenticated_client.post(
                _url("session", reported.pk),
                _post_data(reporter_email="rita.other@example.com"),
            )

        report = ContentReport.objects.get()
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_session_location(reported),
            messages=[(messages.SUCCESS, "Report sent. We emailed you a receipt.")],
        )
        assert report.reporter_id == active_user.pk
        assert list(Notification.objects.values_list("recipient_id", "kind")) == [
            (active_user.pk, NotificationKind.REPORT_RECEIVED.value)
        ]
        assert [mail.to for mail in mailoutbox] == [["rita.other@example.com"]]

    def test_child_abuse_material_can_be_reported_anonymously(
        self, client, session, mailoutbox, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(
                _url("session", session.pk),
                _post_data(
                    reason=ReportReason.CHILD_SEXUAL_ABUSE.value,
                    reporter_name="",
                    reporter_email="",
                ),
            )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_session_location(session),
            messages=[(messages.SUCCESS, "Report sent. Thank you.")],
        )
        assert ContentReport.objects.values_list(
            "reason", "reporter_name", "reporter_email"
        ).get() == (ReportReason.CHILD_SEXUAL_ABUSE, "", "")
        assert mailoutbox == []

    def test_other_reasons_need_a_name_and_email(self, client, session):
        response = client.post(
            _url("session", session.pk), _post_data(reporter_name="", reporter_email="")
        )

        assert_response(
            response,
            HTTPStatus.BAD_REQUEST,
            template_name="report/form.html",
            context_data=_form_context(
                ReportTargetDTO(
                    kind=ReportedContentKind.SESSION,
                    object_id=session.pk,
                    label=session.title,
                    location=_session_location(session),
                )
            )
            | {
                "form": FormErrorsMatcher(
                    reporter_name=[NAME_REQUIRED], reporter_email=[EMAIL_REQUIRED]
                )
            },
        )
        assert not ContentReport.objects.exists()

    def test_the_good_faith_statement_is_required(self, client, session):
        data = _post_data()
        del data["good_faith"]

        response = client.post(_url("session", session.pk), data)

        assert_response(
            response,
            HTTPStatus.BAD_REQUEST,
            template_name="report/form.html",
            context_data=_form_context(
                ReportTargetDTO(
                    kind=ReportedContentKind.SESSION,
                    object_id=session.pk,
                    label=session.title,
                    location=_session_location(session),
                )
            )
            | {"form": FormErrorsMatcher(good_faith=["This field is required."])},
        )
        assert not ContentReport.objects.exists()

    def test_a_foreign_session_takes_no_report(self, client, non_root_sphere):
        foreign = SessionFactory(
            event=EventFactory(sphere=non_root_sphere), category=None
        )

        response = client.post(_url("session", foreign.pk), _post_data())

        assert_response_404(response)
        assert not ContentReport.objects.exists()

    def test_the_rate_limit_stops_a_flood_from_one_address(
        self, client, session, mailoutbox, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            for _ in range(REPORTS_PER_WINDOW):
                Client().post(_url("session", session.pk), _post_data())
            response = client.post(_url("session", session.pk), _post_data())

        assert_response(
            response,
            HTTPStatus.TOO_MANY_REQUESTS,
            template_name="report/form.html",
            context_data=_form_context(
                ReportTargetDTO(
                    kind=ReportedContentKind.SESSION,
                    object_id=session.pk,
                    label=session.title,
                    location=_session_location(session),
                )
            )
            | {"form": FormErrorsMatcher(__all__=[RATE_LIMITED])},
        )
        assert ContentReport.objects.count() == REPORTS_PER_WINDOW
        assert len(mailoutbox) == REPORTS_PER_WINDOW

    def test_another_address_is_counted_apart(self, client, session):
        for _ in range(REPORTS_PER_WINDOW):
            Client().post(_url("session", session.pk), _post_data())

        response = client.post(
            _url("session", session.pk),
            _post_data(),
            HTTP_CF_CONNECTING_IP="203.0.113.7",
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_session_location(session),
            messages=[(messages.SUCCESS, "Report sent. We emailed you a receipt.")],
        )
        assert ContentReport.objects.count() == REPORTS_PER_WINDOW + 1
