"""Reports of illegal content: the intake and the root sphere's queue.

Ways this can fail, one test each:
- a report reaches content its sphere does not show publicly;
- a report is stored without the good-faith statement, or without the name
  and email its reason needs;
- a report of child sexual abuse material is refused for lacking contact;
- one address or account floods the queue past the limit, or one
  reporter's count spills onto another;
- a reporter who left no location gets a report with none;
- the receipt is not sent, or is sent for a report that was refused;
- a sphere other than the root reads or decides a report;
- a report is decided twice, sending two decisions;
- a decision is stored without its email to the reporter.
"""

from datetime import UTC, datetime

import pytest

from ludamus.mills.report import ReportQueueService, ReportService
from ludamus.pacts import NotFoundError
from ludamus.pacts.ids import SphereId, UserId
from ludamus.pacts.report import (
    ContentReportDTO,
    ReportAlreadyDecidedError,
    ReportedContentKind,
    ReporterContactDTO,
    ReportFormDTO,
    ReportIncompleteError,
    ReportRateLimitedError,
    ReportReason,
    ReportStatus,
    ReportSubmission,
    ReportTargetDTO,
)
from ludamus.specs.report import REPORT_WINDOW_SECONDS, REPORTS_PER_WINDOW
from tests.unit.factories import FakeTransaction

ROOT = SphereId(1)
OTHER_SPHERE = SphereId(2)
REPORTER = UserId(7)
MANAGER = UserId(9)
SESSION_PK = 11
TARGET = ReportTargetDTO(
    kind=ReportedContentKind.SESSION,
    object_id=SESSION_PK,
    label="Dragons at dawn",
    location="https://example.com/event/e/?session=11",
)


def _report(**overrides):
    return ContentReportDTO(
        pk=3,
        kind=ReportedContentKind.SESSION,
        object_id=SESSION_PK,
        content_label="Dragons at dawn",
        location=TARGET.location,
        sphere_name="Root",
        reason=ReportReason.HATE_SPEECH,
        explanation="It calls for violence.",
        reporter_name="Rita",
        reporter_email="rita@example.com",
        reporter_user_id=None,
        status=ReportStatus.OPEN,
        decision="",
        decided_by_name="",
        decided_at=None,
        decided_automatically=False,
        creation_time=datetime(2026, 10, 1, tzinfo=UTC),
    ).model_copy(update=overrides)


def _submission(**overrides):
    return ReportSubmission(
        kind=ReportedContentKind.SESSION,
        object_id=SESSION_PK,
        sphere_id=ROOT,
        reason=ReportReason.HATE_SPEECH,
        explanation="  It calls for violence.  ",
        reporter_name=" Rita ",
        reporter_email=" rita@example.com ",
        reporter_user_id=None,
        location="https://example.com/event/e/",
        good_faith=True,
    ).model_copy(update=overrides)


class FakeCache:
    def __init__(self):
        self.store = {}
        self.timeouts = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, timeout=None):
        self.store[key] = value
        self.timeouts[key] = timeout


class StubReports:
    """Answers what a test configures and records what the service writes.

    Which content a sphere shows publicly is the repository's rule, tested
    against the database; here a target is visible because the test says so.
    """

    def __init__(self, *, target=TARGET, report=None):
        self.target = target
        self.report = report
        self.created = []
        self.decided = []

    def read_target(self, *, kind, object_id, sphere_id):
        visible = sphere_id == ROOT and (kind, object_id) == (
            ReportedContentKind.SESSION,
            SESSION_PK,
        )
        return self.target if visible else None

    @staticmethod
    def read_reporter(user_id):
        return ReporterContactDTO(name=f"User {user_id}", email="u@example.com")

    def create(self, data):
        self.created.append(data)
        return _report(
            reason=data.reason,
            reporter_name=data.reporter_name,
            reporter_email=data.reporter_email,
            reporter_user_id=data.reporter_user_id,
            location=data.location,
        )

    def list_by_status(self, status):
        return [self.report] if self.report and self.report.status is status else []

    def read(self, report_id):
        return self.report if self.report and self.report.pk == report_id else None

    def lock(self, report_id):
        return self.read(report_id)

    def mark_decided(self, *, report_id, decided_by_id, decision, now):
        self.decided.append((report_id, decided_by_id, decision))
        return self.report.model_copy(
            update={
                "status": ReportStatus.DECIDED,
                "decision": decision,
                "decided_at": now,
            }
        )


class RecordingNotifier:
    def __init__(self):
        self.received = []
        self.decided = []

    def notify_report_received(self, notification):
        self.received.append(notification)

    def notify_report_decided(self, notification):
        self.decided.append(notification)


def _intake(reports=None, cache=None, notifier=None):
    reports = reports or StubReports()
    cache = cache or FakeCache()
    notifier = notifier or RecordingNotifier()
    service = ReportService(
        transaction=FakeTransaction(), reports=reports, cache=cache, notifier=notifier
    )
    return service, reports, cache, notifier


def _queue(report=None):
    reports = StubReports(report=report)
    notifier = RecordingNotifier()
    service = ReportQueueService(
        transaction=FakeTransaction(), reports=reports, notifier=notifier
    )
    return service, reports, notifier


class TestPrepare:
    def test_a_signed_out_reporter_starts_blank(self):
        service, *_ = _intake()

        page = service.prepare(
            kind=ReportedContentKind.SESSION,
            object_id=SESSION_PK,
            sphere_id=ROOT,
            reporter_user_id=None,
        )

        assert page == ReportFormDTO(
            target=TARGET, reporter=ReporterContactDTO(name="", email="")
        )

    def test_a_signed_in_reporter_starts_from_their_account(self):
        service, *_ = _intake()

        page = service.prepare(
            kind=ReportedContentKind.SESSION,
            object_id=SESSION_PK,
            sphere_id=ROOT,
            reporter_user_id=REPORTER,
        )

        assert page.reporter == ReporterContactDTO(name="User 7", email="u@example.com")

    def test_content_this_sphere_does_not_show_is_not_found(self):
        service, *_ = _intake()

        with pytest.raises(NotFoundError):
            service.prepare(
                kind=ReportedContentKind.SESSION,
                object_id=SESSION_PK,
                sphere_id=OTHER_SPHERE,
                reporter_user_id=None,
            )


class TestSubmit:
    def test_stores_the_report_and_sends_the_receipt(self):
        service, reports, cache, notifier = _intake()

        report = service.submit(_submission(), client_ip="203.0.113.1")

        assert [
            (
                data.target,
                data.explanation,
                data.reporter_name,
                data.reporter_email,
                data.location,
            )
            for data in reports.created
        ] == [
            (
                TARGET,
                "It calls for violence.",
                "Rita",
                "rita@example.com",
                "https://example.com/event/e/",
            )
        ]
        assert [(n.report_id, n.recipient_email) for n in notifier.received] == [
            (report.pk, "rita@example.com")
        ]
        assert (cache.store, cache.timeouts) == (
            {"report_rate:ip:203.0.113.1": 1},
            {"report_rate:ip:203.0.113.1": REPORT_WINDOW_SECONDS},
        )

    def test_no_location_falls_back_to_the_contents_own_page(self):
        service, reports, *_ = _intake()

        service.submit(_submission(location=""), client_ip="203.0.113.1")

        assert reports.created[0].location == TARGET.location

    def test_hidden_content_takes_no_report(self):
        service, reports, _, notifier = _intake()

        with pytest.raises(NotFoundError):
            service.submit(_submission(sphere_id=OTHER_SPHERE), client_ip="203.0.113.1")

        assert (reports.created, notifier.received) == ([], [])

    @pytest.mark.parametrize(
        "overrides",
        (
            {"good_faith": False},
            {"reporter_name": "  "},
            {"reporter_email": ""},
            {"reason": ReportReason.CHILD_SEXUAL_ABUSE, "good_faith": False},
        ),
    )
    def test_an_incomplete_report_is_refused(self, overrides):
        service, reports, _, notifier = _intake()

        with pytest.raises(ReportIncompleteError):
            service.submit(_submission(**overrides), client_ip="203.0.113.1")

        assert (reports.created, notifier.received) == ([], [])

    def test_child_abuse_material_needs_no_contact(self):
        service, reports, *_ = _intake()

        service.submit(
            _submission(
                reason=ReportReason.CHILD_SEXUAL_ABUSE,
                reporter_name="",
                reporter_email="",
            ),
            client_ip="203.0.113.1",
        )

        assert [(d.reporter_name, d.reporter_email) for d in reports.created] == [
            ("", "")
        ]

    def test_the_limit_stops_one_address(self):
        cache = FakeCache()
        service, reports, _, notifier = _intake(cache=cache)
        for _ in range(REPORTS_PER_WINDOW):
            service.submit(_submission(), client_ip="203.0.113.1")

        with pytest.raises(ReportRateLimitedError):
            service.submit(_submission(), client_ip="203.0.113.1")

        assert len(reports.created) == len(notifier.received) == REPORTS_PER_WINDOW

    def test_a_signed_in_reporter_is_counted_by_account_not_address(self):
        cache = FakeCache()
        service, reports, *_ = _intake(cache=cache)
        for _ in range(REPORTS_PER_WINDOW):
            service.submit(_submission(), client_ip="203.0.113.1")

        service.submit(_submission(reporter_user_id=REPORTER), client_ip="203.0.113.1")

        assert cache.store == {
            "report_rate:ip:203.0.113.1": REPORTS_PER_WINDOW,
            "report_rate:user:7": 1,
        }
        assert len(reports.created) == REPORTS_PER_WINDOW + 1


class TestQueue:
    def test_lists_open_reports_on_the_root(self):
        service, *_ = _queue(report=_report())

        assert service.list_open(sphere_id=ROOT, root_sphere_id=ROOT) == [_report()]

    def test_reads_one_report_on_the_root(self):
        service, *_ = _queue(report=_report())

        assert service.read(sphere_id=ROOT, root_sphere_id=ROOT, report_id=3) == (
            _report()
        )

    def test_an_unknown_report_is_not_found(self):
        service, *_ = _queue(report=_report())

        with pytest.raises(NotFoundError):
            service.read(sphere_id=ROOT, root_sphere_id=ROOT, report_id=4)

    @pytest.mark.parametrize("action", ("list", "read", "decide"))
    def test_another_sphere_reaches_nothing(self, action):
        service, reports, notifier = _queue(report=_report())
        calls = {
            "list": lambda: service.list_open(
                sphere_id=OTHER_SPHERE, root_sphere_id=ROOT
            ),
            "read": lambda: service.read(
                sphere_id=OTHER_SPHERE, root_sphere_id=ROOT, report_id=3
            ),
            "decide": lambda: service.decide(
                sphere_id=OTHER_SPHERE,
                root_sphere_id=ROOT,
                report_id=3,
                decided_by_id=MANAGER,
                decision="Removed.",
            ),
        }

        with pytest.raises(NotFoundError):
            calls[action]()

        assert (reports.decided, notifier.decided) == ([], [])

    def test_deciding_records_it_and_tells_the_reporter(self):
        service, reports, notifier = _queue(report=_report())

        decided = service.decide(
            sphere_id=ROOT,
            root_sphere_id=ROOT,
            report_id=3,
            decided_by_id=MANAGER,
            decision="  Removed: it called for violence.  ",
        )

        assert reports.decided == [(3, MANAGER, "Removed: it called for violence.")]
        assert [
            (n.report_id, n.recipient_email, n.decision, n.decided_automatically)
            for n in notifier.decided
        ] == [(3, "rita@example.com", "Removed: it called for violence.", False)]
        assert decided.status is ReportStatus.DECIDED

    def test_deciding_an_unknown_report_is_not_found(self):
        service, reports, notifier = _queue(report=None)

        with pytest.raises(NotFoundError):
            service.decide(
                sphere_id=ROOT,
                root_sphere_id=ROOT,
                report_id=3,
                decided_by_id=MANAGER,
                decision="Removed.",
            )

        assert (reports.decided, notifier.decided) == ([], [])

    def test_a_decided_report_is_not_decided_again(self):
        service, reports, notifier = _queue(
            report=_report(
                status=ReportStatus.DECIDED,
                decided_at=datetime(2026, 10, 2, tzinfo=UTC),
            )
        )

        with pytest.raises(ReportAlreadyDecidedError):
            service.decide(
                sphere_id=ROOT,
                root_sphere_id=ROOT,
                report_id=3,
                decided_by_id=MANAGER,
                decision="Again.",
            )

        assert (reports.decided, notifier.decided) == ([], [])
