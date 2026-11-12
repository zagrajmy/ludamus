from datetime import UTC, datetime

import pytest

from ludamus.mills.moderation import (
    ActiveRecipientsService,
    ChatReportIntakeService,
    ModerationDecisionService,
    NoticeService,
    StatementOfReasonsService,
)
from ludamus.pacts.moderation import (
    ChatReportDTO,
    ContentNoticeData,
    ContentNoticeDTO,
    InvalidVerdictError,
    ModerationDecision,
    ModerationGround,
    ModerationSource,
    ModerationStatus,
    ModerationVerdict,
    NoticeCategory,
    NoticeOutcome,
    StatementOfReasons,
)
from ludamus.specs.moderation import NOTICES_PER_ADDRESS
from tests.unit.encounter_fakes import FakeCache
from tests.unit.factories import FakeTransaction

IP = "203.0.113.7"
REPORTER_ID = 3
AUTHOR_ID = 4
FIRST_CASE_ID = 101
GIVEN_CASE_ID = 7


class FakeCases:
    def __init__(self):
        self.opened = 0

    def open(self):
        self.opened += 1
        return 100 + self.opened


class FakeNotices:
    def __init__(self, *notices):
        self.rows = {notice.pk: notice for notice in notices}
        self.created = []
        self.decisions = {}

    def create(self, data):
        self.created.append(data)
        notice = ContentNoticeDTO(
            pk=len(self.created),
            case_id=data["case_id"],
            url=data["url"],
            category=data["category"],
            explanation=data["explanation"],
            reporter_email=data["reporter_email"],
            language=data["language"],
            status=ModerationStatus.OPEN,
        )
        self.rows[notice.pk] = notice
        return notice

    def read(self, pk):
        return self.rows[pk]

    def decide(self, pk, decision):
        if self.rows[pk].status != ModerationStatus.OPEN or pk in self.decisions:
            return False
        self.decisions[pk] = decision
        return True


class FakeReports:
    def __init__(self, *reports, attachable=True):
        self.rows = {report.pk: report for report in reports}
        self.attachable = attachable
        self.attached = {}
        self.decisions = {}

    def read_by_message(self, *, reporter_id, room_id, message_id):
        return next(
            (
                report
                for report in self.rows.values()
                if report.reporter_id == reporter_id
                and report.room_id == room_id
                and message_id == 1
            ),
            None,
        )

    def read(self, pk):
        return self.rows[pk]

    def attach_case(self, *, pk, case_id):
        if self.attachable:
            self.attached[pk] = case_id
        return self.attachable

    def decide(self, pk, decision):
        if pk in self.decisions:
            return False
        self.decisions[pk] = decision
        return True


class FakeStatements:
    def __init__(self):
        self.created = []

    def create(self, data):
        self.created.append(data)
        return len(self.created)


class FakeMailer:
    def __init__(self):
        self.alerts = []
        self.receipts = []
        self.outcomes = []
        self.statements = []

    def alert_staff(self, alert):
        self.alerts.append(alert)

    def send_receipt(self, receipt):
        self.receipts.append(receipt)

    def send_outcome(self, outcome):
        self.outcomes.append(outcome)

    def send_statement(self, *, statement, case_id):
        self.statements.append((statement, case_id))


def _notice_data(**overrides):
    return ContentNoticeData(
        **{
            "url": " https://zagrajmy.net/event/x/ ",
            "category": NoticeCategory.FRAUD,
            "explanation": " A fake ticket shop. ",
            "reporter_name": "Ola",
            "reporter_email": "ola@example.com",
            "reporter_id": None,
            "sphere_id": 1,
            "language": "pl",
        }
        | overrides
    )


def _notice(pk=1, **overrides):
    return ContentNoticeDTO(
        **{
            "pk": pk,
            "case_id": 7,
            "url": "https://zagrajmy.net/event/x/",
            "category": NoticeCategory.FRAUD,
            "explanation": "A fake ticket shop.",
            "reporter_email": "ola@example.com",
            "language": "pl",
            "status": ModerationStatus.OPEN,
        }
        | overrides
    )


def _report(pk=1, **overrides):
    return ChatReportDTO(
        **{
            "pk": pk,
            "case_id": 9,
            "reporter_id": REPORTER_ID,
            "reported_user_id": AUTHOR_ID,
            "room_id": "sphere:1",
            "author_name": "Kuba",
            "body": "Words",
            "reason": "Insults",
            "status": ModerationStatus.OPEN,
        }
        | overrides
    )


def _actioned(**overrides):
    return ModerationVerdict(
        **{
            "status": ModerationStatus.ACTIONED,
            "decision": ModerationDecision.CONTENT_REMOVED,
            "ground": ModerationGround.ILLEGAL_CONTENT,
            "decision_text": " The shop sold fake tickets. ",
        }
        | overrides
    )


class TestNoticeService:
    @staticmethod
    def _service(*, cache=None, mailer=None, notices=None, cases=None):
        return NoticeService(
            transaction=FakeTransaction(),
            cases=cases or FakeCases(),
            notices=notices or FakeNotices(),
            cache=cache or FakeCache(),
            mailer=mailer or FakeMailer(),
        )

    def test_files_a_notice_under_a_new_case_and_tells_staff_and_the_reporter(self):
        mailer, notices = FakeMailer(), FakeNotices()

        submission = self._service(mailer=mailer, notices=notices).submit(
            _notice_data(), ip_address=IP
        )

        assert submission.outcome == NoticeOutcome.CREATED
        assert submission.case_reference == "Z-101"
        assert notices.created == [
            {
                "case_id": 101,
                "url": "https://zagrajmy.net/event/x/",
                "category": NoticeCategory.FRAUD,
                "explanation": "A fake ticket shop.",
                "reporter_name": "Ola",
                "reporter_email": "ola@example.com",
                "reporter_id": None,
                "sphere_id": 1,
                "language": "pl",
            }
        ]
        assert [(a.source, a.urgent, a.location) for a in mailer.alerts] == [
            (ModerationSource.NOTICE, False, "https://zagrajmy.net/event/x/")
        ]
        assert [(r.case_id, r.address, r.language) for r in mailer.receipts] == [
            (101, "ola@example.com", "pl")
        ]

    @pytest.mark.parametrize(
        ("name", "email"), (("", "ola@example.com"), ("Ola", " "), ("", ""))
    )
    def test_a_notice_without_contact_is_refused_unless_it_is_csam(self, name, email):
        notices = FakeNotices()

        submission = self._service(notices=notices).submit(
            _notice_data(reporter_name=name, reporter_email=email), ip_address=IP
        )

        assert submission.outcome == NoticeOutcome.CONTACT_REQUIRED
        assert not notices.created

    def test_csam_may_be_reported_anonymously_and_is_urgent(self):
        mailer = FakeMailer()

        submission = self._service(mailer=mailer).submit(
            _notice_data(
                category=NoticeCategory.CHILD_SEXUAL_ABUSE,
                reporter_name="",
                reporter_email="",
            ),
            ip_address=IP,
        )

        assert submission.outcome == NoticeOutcome.CREATED
        assert [alert.urgent for alert in mailer.alerts] == [True]
        assert not mailer.receipts

    def test_child_safety_is_urgent(self):
        mailer = FakeMailer()

        self._service(mailer=mailer).submit(
            _notice_data(category=NoticeCategory.CHILD_SAFETY), ip_address=IP
        )

        assert [alert.urgent for alert in mailer.alerts] == [True]

    def test_one_address_is_throttled_past_the_limit_while_another_is_not(self):
        cache, notices = FakeCache(), FakeNotices()
        service = self._service(cache=cache, notices=notices)
        for _ in range(NOTICES_PER_ADDRESS):
            service.submit(_notice_data(), ip_address=IP)

        throttled = service.submit(_notice_data(), ip_address=IP)
        elsewhere = service.submit(_notice_data(), ip_address="198.51.100.1")

        assert throttled.outcome == NoticeOutcome.THROTTLED
        assert elsewhere.outcome == NoticeOutcome.CREATED
        assert len(notices.created) == NOTICES_PER_ADDRESS + 1
        assert IP not in "".join(cache.entries)


class TestChatReportIntakeService:
    @staticmethod
    def _service(reports, *, mailer=None, cases=None):
        return ChatReportIntakeService(
            transaction=FakeTransaction(),
            cases=cases or FakeCases(),
            reports=reports,
            mailer=mailer or FakeMailer(),
        )

    def _take(self, service):
        service.take(reporter_id=REPORTER_ID, room_id="sphere:1", message_id=1)

    def test_a_new_report_opens_a_case_and_tells_staff(self):
        reports, mailer = FakeReports(_report(case_id=None)), FakeMailer()

        self._take(self._service(reports, mailer=mailer))

        assert reports.attached == {1: 101}
        assert [
            (a.case_id, a.source, a.record_id, a.category, a.urgent, a.explanation)
            for a in mailer.alerts
        ] == [(101, ModerationSource.CHAT_REPORT, 1, None, False, "Insults")]

    @pytest.mark.parametrize(
        "reports",
        (
            FakeReports(),
            FakeReports(_report(case_id=5)),
            FakeReports(_report(case_id=None), attachable=False),
        ),
        ids=["no-report", "already-filed", "filed-meanwhile"],
    )
    def test_staff_hear_of_each_report_once(self, reports):
        mailer = FakeMailer()

        self._take(self._service(reports, mailer=mailer))

        assert not mailer.alerts


class TestStatementOfReasonsService:
    @staticmethod
    def _statement(**overrides):
        return StatementOfReasons(
            **{
                "user_id": AUTHOR_ID,
                "case_id": None,
                "decision": ModerationDecision.ACCOUNT_SUSPENDED,
                "ground": ModerationGround.TERMS_MULTIPLE_ACCOUNTS,
                "facts": " Three accounts enrolled in one seat. ",
                "from_report": False,
            }
            | overrides
        )

    def test_records_and_mails_a_statement_under_a_new_case(self):
        statements, mailer = FakeStatements(), FakeMailer()
        service = StatementOfReasonsService(
            transaction=FakeTransaction(),
            cases=FakeCases(),
            statements=statements,
            mailer=mailer,
        )

        case_id = service.issue(self._statement())

        assert case_id == FIRST_CASE_ID
        assert statements.created == [
            {
                "case_id": 101,
                "user_id": AUTHOR_ID,
                "decision": ModerationDecision.ACCOUNT_SUSPENDED,
                "ground": ModerationGround.TERMS_MULTIPLE_ACCOUNTS,
                "facts": "Three accounts enrolled in one seat.",
                "from_report": False,
                "automated": False,
            }
        ]
        assert [case for __, case in mailer.statements] == [101]

    def test_keeps_the_case_it_was_given(self):
        cases = FakeCases()
        service = StatementOfReasonsService(
            transaction=FakeTransaction(),
            cases=cases,
            statements=FakeStatements(),
            mailer=FakeMailer(),
        )

        assert service.issue(self._statement(case_id=GIVEN_CASE_ID)) == GIVEN_CASE_ID
        assert cases.opened == 0

    def test_no_action_needs_no_statement(self):
        mailer = FakeMailer()
        service = StatementOfReasonsService(
            transaction=FakeTransaction(),
            cases=FakeCases(),
            statements=FakeStatements(),
            mailer=mailer,
        )

        with pytest.raises(InvalidVerdictError):
            service.issue(self._statement(decision=ModerationDecision.NO_ACTION))
        assert not mailer.statements


class TestModerationDecisionService:
    @staticmethod
    def _service(*, notices=None, reports=None, mailer=None, cases=None):
        mailer = mailer or FakeMailer()
        cases = cases or FakeCases()
        statements = StatementOfReasonsService(
            transaction=FakeTransaction(),
            cases=cases,
            statements=FakeStatements(),
            mailer=mailer,
        )
        return ModerationDecisionService(
            transaction=FakeTransaction(),
            cases=cases,
            notices=notices or FakeNotices(),
            reports=reports or FakeReports(),
            statements=statements,
            mailer=mailer,
        )

    def test_an_actioned_notice_tells_the_reporter_and_explains_to_the_author(self):
        notices, mailer = FakeNotices(_notice()), FakeMailer()

        decided = self._service(notices=notices, mailer=mailer).decide_notices(
            notice_ids=[1], verdict=_actioned(), affected_user_id=AUTHOR_ID
        )

        assert decided == 1
        decision = notices.decisions[1]
        assert (
            decision["status"],
            decision["decision"],
            decision["ground"],
            decision["decision_text"],
        ) == (
            ModerationStatus.ACTIONED,
            ModerationDecision.CONTENT_REMOVED,
            "illegal_content",
            "The shop sold fake tickets.",
        )
        assert [
            (o.case_id, o.status, o.address, o.language, o.reporter_id)
            for o in mailer.outcomes
        ] == [(7, ModerationStatus.ACTIONED, "ola@example.com", "pl", None)]
        assert [
            (s.user_id, s.decision, s.ground, s.from_report, case)
            for s, case in mailer.statements
        ] == [
            (
                AUTHOR_ID,
                ModerationDecision.CONTENT_REMOVED,
                ModerationGround.ILLEGAL_CONTENT,
                True,
                7,
            )
        ]

    def test_a_rejected_notice_records_no_action_and_explains_to_nobody(self):
        notices, mailer = FakeNotices(_notice()), FakeMailer()

        self._service(notices=notices, mailer=mailer).decide_notices(
            notice_ids=[1],
            verdict=_actioned(status=ModerationStatus.REJECTED),
            affected_user_id=AUTHOR_ID,
        )

        assert (notices.decisions[1]["decision"], notices.decisions[1]["ground"]) == (
            ModerationDecision.NO_ACTION,
            "",
        )
        assert [o.status for o in mailer.outcomes] == [ModerationStatus.REJECTED]
        assert not mailer.statements

    def test_a_closed_notice_is_left_alone_and_an_anonymous_one_mails_nobody(self):
        notices = FakeNotices(
            _notice(1, status=ModerationStatus.REJECTED),
            _notice(2, reporter_email="", case_id=None),
        )
        mailer, cases = FakeMailer(), FakeCases()

        decided = self._service(
            notices=notices, mailer=mailer, cases=cases
        ).decide_notices(notice_ids=[1, 2], verdict=_actioned(), affected_user_id=None)

        assert decided == 1
        assert list(notices.decisions) == [2]
        assert not mailer.outcomes
        assert not mailer.statements
        assert cases.opened == 1

    def test_a_chat_report_tells_its_reporter_and_explains_to_the_author(self):
        reports, mailer = FakeReports(_report()), FakeMailer()

        decided = self._service(reports=reports, mailer=mailer).decide_chat_reports(
            report_ids=[1], verdict=_actioned(decision=ModerationDecision.WARNING)
        )

        assert decided == 1
        assert [(o.case_id, o.reporter_id, o.address) for o in mailer.outcomes] == [
            (9, REPORTER_ID, "")
        ]
        assert [(s.user_id, s.decision, case) for s, case in mailer.statements] == [
            (AUTHOR_ID, ModerationDecision.WARNING, 9)
        ]

    def test_a_chat_report_already_closed_or_without_an_author_explains_nothing(self):
        reports = FakeReports(_report(1), _report(2, reported_user_id=None))
        reports.decisions[1] = {}
        mailer = FakeMailer()

        decided = self._service(reports=reports, mailer=mailer).decide_chat_reports(
            report_ids=[1, 2], verdict=_actioned()
        )

        assert decided == 1
        assert [o.case_id for o in mailer.outcomes] == [9]
        assert not mailer.statements

    @pytest.mark.parametrize(
        "verdict",
        (
            _actioned(status=ModerationStatus.OPEN),
            _actioned(decision=ModerationDecision.NO_ACTION),
            _actioned(ground=None),
            _actioned(decision_text="  "),
        ),
        ids=["still-open", "action-without-measure", "action-without-ground", "silent"],
    )
    def test_an_incoherent_verdict_changes_nothing(self, verdict):
        notices, mailer = FakeNotices(_notice()), FakeMailer()

        with pytest.raises(InvalidVerdictError):
            self._service(notices=notices, mailer=mailer).decide_notices(
                notice_ids=[1], verdict=verdict, affected_user_id=AUTHOR_ID
            )
        assert not notices.decisions
        assert not mailer.outcomes


class FakeActivity:
    def __init__(self):
        self.windows = []

    def count_active_accounts(self, *, start, end):
        self.windows.append((start, end))
        return start.month


def test_monthly_average_covers_the_six_full_months_before_this_one():
    activity = FakeActivity()

    report = ActiveRecipientsService(repository=activity).monthly_average(
        now=datetime(2026, 3, 15, 12, tzinfo=UTC)
    )

    assert [start for start, __ in report.months] == [
        datetime(2025, month, 1, tzinfo=UTC) for month in range(9, 13)
    ] + [datetime(2026, month, 1, tzinfo=UTC) for month in (1, 2)]
    assert activity.windows[-1] == (
        datetime(2026, 2, 1, tzinfo=UTC),
        datetime(2026, 3, 1, tzinfo=UTC),
    )
    assert report.average == pytest.approx((9 + 10 + 11 + 12 + 1 + 2) / 6)
