from datetime import UTC, datetime
from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from ludamus.links.db.django.models import (
    ContentReport,
    Notification,
    Session,
    SphereMembership,
)
from ludamus.pacts.legacy import NotificationKind
from ludamus.pacts.multiverse import SphereRole
from ludamus.pacts.report import (
    ContentReportDTO,
    ReportedContentKind,
    ReportReason,
    ReportStatus,
)
from tests.integration.conftest import EventFactory, SessionFactory, UserFactory
from tests.integration.utils import (
    FormErrorsMatcher,
    assert_login_required,
    assert_response,
    assert_response_404,
)
from tests.integration.web.multiverse.helpers import (
    READ_ONLY_ROLE_ERROR,
    assert_not_a_sphere_manager,
    sphere_sidebar_context,
)

REPORTS_URL = reverse("multiverse:panel:reports")
DECISION = "We removed the description: it called for violence."


def _detail_url(report):
    return reverse("multiverse:panel:report-detail", kwargs={"pk": report.pk})


def _decide_url(report):
    return reverse("multiverse:panel:report-decide", kwargs={"pk": report.pk})


def _report(session, *, sphere, **fields):
    return ContentReport.objects.create(
        sphere=sphere,
        content_type=ContentType.objects.get_for_model(Session),
        object_id=session.pk,
        content_label=session.title,
        location=f"https://testserver/event/{session.event.slug}/?session={session.pk}",
        reason=fields.pop("reason", ReportReason.HATE_SPEECH),
        explanation="It calls for violence.",
        reporter_name=fields.pop("reporter_name", "Rita Reporter"),
        reporter_email=fields.pop("reporter_email", "rita@example.com"),
        good_faith=True,
        **fields,
    )


def _dto(report, **overrides):
    return ContentReportDTO(
        pk=report.pk,
        kind=ReportedContentKind.SESSION,
        object_id=report.object_id,
        content_label=report.content_label,
        location=report.location,
        sphere_name=report.sphere.name,
        reason=ReportReason(report.reason),
        explanation=report.explanation,
        reporter_name=report.reporter_name,
        reporter_email=report.reporter_email,
        reporter_user_id=None,
        status=ReportStatus.OPEN,
        decision="",
        decided_by_name="",
        decided_at=None,
        decided_automatically=False,
        creation_time=report.creation_time,
    ).model_copy(update=overrides)


@pytest.fixture(name="manager")
def manager_fixture(active_user, sphere):
    SphereMembership.objects.create(
        sphere=sphere, user=active_user, role=SphereRole.MANAGER
    )
    return active_user


# The reported content lives in another sphere: the root's queue holds every
# sphere's reports, and the root's own panel lists no events of its own.
@pytest.fixture(name="reported_session")
def reported_session_fixture(non_root_sphere):
    return SessionFactory(event=EventFactory(sphere=non_root_sphere), category=None)


@pytest.fixture(name="report")
def report_fixture(reported_session, non_root_sphere):
    return _report(reported_session, sphere=non_root_sphere)


class TestReportsPageView:
    def test_redirects_anonymous_user_to_login(self, client):
        response = client.get(REPORTS_URL)

        assert_login_required(response, REPORTS_URL)

    def test_refuses_a_stranger(self, authenticated_client):
        response = authenticated_client.get(REPORTS_URL)

        assert_not_a_sphere_manager(response)

    def test_a_root_manager_sees_open_reports_oldest_first(
        self, authenticated_client, manager, report, reported_session, non_root_sphere
    ):
        _report(
            reported_session,
            sphere=non_root_sphere,
            status=ReportStatus.DECIDED,
            decided_at=datetime.now(UTC),
        )
        newer = _report(
            reported_session, sphere=non_root_sphere, reason=ReportReason.SCAM
        )

        response = authenticated_client.get(REPORTS_URL)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/content_reports/list.html",
            context_data={
                **sphere_sidebar_context(active_nav="reports"),
                "reports": [_dto(report), _dto(newer)],
            },
        )

    def test_another_spheres_manager_finds_no_queue(
        self, client, non_root_sphere, report
    ):
        outsider = UserFactory()
        SphereMembership.objects.create(
            sphere=non_root_sphere, user=outsider, role=SphereRole.MANAGER
        )
        client.force_login(outsider)

        response = client.get(REPORTS_URL, HTTP_HOST=non_root_sphere.site.domain)

        assert_response_404(response)


class TestReportDetailPageView:
    def test_shows_an_open_report_with_the_decision_form(
        self, authenticated_client, manager, report
    ):
        response = authenticated_client.get(_detail_url(report))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/content_reports/detail.html",
            context_data={
                **sphere_sidebar_context(active_nav="reports"),
                "report": _dto(report),
                "form": ANY,
            },
        )

    def test_a_decided_report_has_no_form(
        self, authenticated_client, manager, reported_session, non_root_sphere
    ):
        decided = _report(
            reported_session,
            sphere=non_root_sphere,
            status=ReportStatus.DECIDED,
            decided_at=datetime.now(UTC),
            decided_by=manager,
            decision=DECISION,
        )

        response = authenticated_client.get(_detail_url(decided))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/content_reports/detail.html",
            context_data={
                **sphere_sidebar_context(active_nav="reports"),
                "report": _dto(
                    decided,
                    status=ReportStatus.DECIDED,
                    decision=DECISION,
                    decided_by_name="Test User",
                    decided_at=decided.decided_at,
                ),
                "form": None,
            },
        )

    def test_an_unknown_report_is_not_found(self, authenticated_client, manager):
        response = authenticated_client.get(
            reverse("multiverse:panel:report-detail", kwargs={"pk": 404})
        )

        assert_response_404(response)


class TestReportDecideActionView:
    def test_deciding_records_it_and_emails_the_reporter(
        self,
        authenticated_client,
        manager,
        report,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            response = authenticated_client.post(
                _decide_url(report), {"decision": DECISION}
            )

        report.refresh_from_db()
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=REPORTS_URL,
            messages=[
                (
                    messages.SUCCESS,
                    "Report decided. We emailed the reporter your decision.",
                )
            ],
        )
        assert (
            report.status,
            report.decision,
            report.decided_by_id,
            report.decided_at is not None,
            report.decided_automatically,
        ) == (ReportStatus.DECIDED, DECISION, manager.pk, True, False)
        assert [(mail.to, mail.subject) for mail in mailoutbox] == [
            (["rita@example.com"], f"Decision on your report #{report.pk}")
        ]
        assert DECISION in mailoutbox[0].body

    def test_a_signed_in_reporter_also_gets_the_bell(
        self,
        authenticated_client,
        manager,
        reported_session,
        non_root_sphere,
        django_capture_on_commit_callbacks,
    ):
        reporter = UserFactory()
        report = _report(reported_session, sphere=non_root_sphere, reporter=reporter)

        with django_capture_on_commit_callbacks(execute=True):
            authenticated_client.post(_decide_url(report), {"decision": DECISION})

        assert list(Notification.objects.values_list("recipient_id", "kind")) == [
            (reporter.pk, NotificationKind.REPORT_DECIDED.value)
        ]

    def test_an_anonymous_report_is_decided_without_email(
        self,
        authenticated_client,
        manager,
        reported_session,
        non_root_sphere,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        report = _report(
            reported_session,
            sphere=non_root_sphere,
            reason=ReportReason.CHILD_SEXUAL_ABUSE,
            reporter_name="",
            reporter_email="",
        )

        with django_capture_on_commit_callbacks(execute=True):
            response = authenticated_client.post(
                _decide_url(report), {"decision": DECISION}
            )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=REPORTS_URL,
            messages=[
                (
                    messages.SUCCESS,
                    "Report decided. The reporter left no email to send it to.",
                )
            ],
        )
        assert mailoutbox == []

    def test_an_empty_decision_is_refused(self, authenticated_client, manager, report):
        response = authenticated_client.post(_decide_url(report), {"decision": "  "})

        report.refresh_from_db()
        assert_response(
            response,
            HTTPStatus.BAD_REQUEST,
            template_name="multiverse/panel/content_reports/detail.html",
            context_data={
                **sphere_sidebar_context(active_nav="reports"),
                "report": _dto(report),
                "form": FormErrorsMatcher(decision=["This field is required."]),
            },
        )
        assert report.status == ReportStatus.OPEN

    def test_a_decided_report_keeps_its_first_decision(
        self,
        authenticated_client,
        manager,
        reported_session,
        non_root_sphere,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        decided = _report(
            reported_session,
            sphere=non_root_sphere,
            status=ReportStatus.DECIDED,
            decided_at=datetime.now(UTC),
            decision=DECISION,
        )

        with django_capture_on_commit_callbacks(execute=True):
            response = authenticated_client.post(
                _decide_url(decided), {"decision": "Changed my mind."}
            )

        decided.refresh_from_db()
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_detail_url(decided),
            messages=[
                (
                    messages.ERROR,
                    "Someone already decided this report. Their decision stands.",
                )
            ],
        )
        assert decided.decision == DECISION
        assert mailoutbox == []

    def test_a_comms_member_cannot_decide(
        self, authenticated_client, active_user, sphere, report
    ):
        SphereMembership.objects.create(
            sphere=sphere, user=active_user, role=SphereRole.COMMS
        )

        response = authenticated_client.post(
            _decide_url(report), {"decision": DECISION}
        )

        report.refresh_from_db()
        assert_response(
            response,
            HTTPStatus.FOUND,
            url="/",
            messages=[(messages.ERROR, READ_ONLY_ROLE_ERROR)],
        )
        assert report.status == ReportStatus.OPEN

    def test_another_spheres_manager_cannot_decide_a_report(
        self,
        client,
        non_root_sphere,
        report,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        outsider = UserFactory()
        SphereMembership.objects.create(
            sphere=non_root_sphere, user=outsider, role=SphereRole.MANAGER
        )
        client.force_login(outsider)

        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(
                _decide_url(report),
                {"decision": DECISION},
                HTTP_HOST=non_root_sphere.site.domain,
            )

        report.refresh_from_db()
        assert_response_404(response)
        assert (report.status, report.decision) == (ReportStatus.OPEN, "")
        assert mailoutbox == []
        assert not Notification.objects.exists()
