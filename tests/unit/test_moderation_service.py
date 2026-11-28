from datetime import UTC, date, datetime

import pytest

from ludamus.mills.moderation import (
    ActiveRecipientsService,
    ChatReportIntakeService,
    ModerationDecisionService,
    NoticeService,
    StatementOfReasonsService,
)
from ludamus.pacts.moderation import (
    CaseStatus,
    ChatReportDTO,
    ContentNoticeData,
    ContentNoticeDTO,
    InvalidVerdictError,
    IssuedStatement,
    ModerationDecision,
    ModerationGround,
    ModerationSource,
    ModerationStatus,
    ModerationVerdict,
    NoticeCategory,
    NoticeOutcome,
    StatementOfReasons,
)
from ludamus.specs.moderation import NOTICES_PER_ADDRESS, RECEIPTS_PER_ADDRESS
from tests.unit.factories import FakeTransaction

IP = "203.0.113.7"
REPORTER_ID = 3
AUTHOR_ID = 4
FIRST_CASE_ID = 101
GIVEN_CASE_ID = 7
PROVISION = "art. 286 § 1 Kodeksu karnego"
LAST_DAY = date(2026, 12, 31)


class FakeCounter:
    def __init__(self):
        self.hits = {}
        self.windows = {}

    def hit(self, key, *, window_seconds):
        self.hits[key] = self.hits.get(key, 0) + 1
        self.windows[key] = window_seconds
        return self.hits[key]


class FakeCases:
    def __init__(self):
        self.opened = 0
        self.closed = 0

    def open(self, *, status):
        self.opened += 1
        self.closed += status == CaseStatus.CLOSED
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
                if (report.reporter_id, report.room_id, report.message_id)
                == (reporter_id, room_id, message_id)
            ),
            None,
        )

    def case_of_message(self, *, room_id, message_id):
        return next(
            (
                report.case_id
                for report in self.rows.values()
                if (report.room_id, report.message_id) == (room_id, message_id)
                and report.case_id is not None
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

    def exists(self, *, case_id, user_id):
        return any(
            (row["case_id"], row["user_id"]) == (case_id, user_id)
            for row in self.created
        )


class FakeMailer:
    def __init__(self, *, reachable=True):
        self.reachable = reachable
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
        return self.reachable


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
            "message_id": 1,
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
            "legal_provision": f" {PROVISION} ",
            "decision_text": " The shop sold fake tickets. ",
        }
        | overrides
    )


class TestNoticeService:
    @staticmethod
    def _service(*, counter=None, mailer=None, notices=None):
        return NoticeService(
            transaction=FakeTransaction(),
            cases=FakeCases(),
            notices=notices or FakeNotices(),
            counter=counter or FakeCounter(),
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
    def test_a_notice_without_contact_is_refused_unless_it_is_about_a_child(
        self, name, email
    ):
        notices = FakeNotices()

        submission = self._service(notices=notices).submit(
            _notice_data(reporter_name=name, reporter_email=email), ip_address=IP
        )

        assert submission.outcome == NoticeOutcome.CONTACT_REQUIRED
        assert not notices.created

    @pytest.mark.parametrize(
        "category", (NoticeCategory.CHILD_SEXUAL_ABUSE, NoticeCategory.CHILD_SAFETY)
    )
    def test_abuse_or_grooming_of_a_child_may_be_reported_anonymously_and_is_urgent(
        self, category
    ):
        mailer = FakeMailer()

        submission = self._service(mailer=mailer).submit(
            _notice_data(category=category, reporter_name="", reporter_email=""),
            ip_address=IP,
        )

        assert submission.outcome == NoticeOutcome.CREATED
        assert [alert.urgent for alert in mailer.alerts] == [True]
        assert not mailer.receipts

    def test_one_address_is_throttled_past_the_limit_while_another_is_not(self):
        counter, notices = FakeCounter(), FakeNotices()
        service = self._service(counter=counter, notices=notices)
        for _ in range(NOTICES_PER_ADDRESS):
            service.submit(_notice_data(), ip_address=IP)

        throttled = service.submit(_notice_data(), ip_address=IP)
        elsewhere = service.submit(_notice_data(), ip_address="198.51.100.1")

        assert throttled.outcome == NoticeOutcome.THROTTLED
        assert elsewhere.outcome == NoticeOutcome.CREATED
        assert len(notices.created) == NOTICES_PER_ADDRESS + 1
        assert IP not in "".join(counter.hits)

    def test_an_ipv6_sender_is_counted_by_its_slash_64(self):
        notices = FakeNotices()
        service = self._service(notices=notices)
        for host in range(NOTICES_PER_ADDRESS):
            service.submit(_notice_data(), ip_address=f"2001:db8:1:2::{host + 1}")

        same_network = service.submit(_notice_data(), ip_address="2001:db8:1:2:ffff::9")
        next_network = service.submit(_notice_data(), ip_address="2001:db8:1:3::1")

        assert same_network.outcome == NoticeOutcome.THROTTLED
        assert next_network.outcome == NoticeOutcome.CREATED

    def test_an_unparsable_sender_is_still_counted(self):
        service = self._service()
        for _ in range(NOTICES_PER_ADDRESS):
            service.submit(_notice_data(), ip_address="")

        assert (
            service.submit(_notice_data(), ip_address="").outcome
            == NoticeOutcome.THROTTLED
        )

    def test_receipts_to_one_address_are_capped_but_the_notices_are_kept(self):
        mailer, notices = FakeMailer(), FakeNotices()
        service = self._service(mailer=mailer, notices=notices)

        for sender in range(RECEIPTS_PER_ADDRESS + 1):
            email = "Victim@Example.com" if sender % 2 else "victim@example.com"
            service.submit(
                _notice_data(reporter_email=email), ip_address=f"198.51.100.{sender}"
            )

        assert len(notices.created) == RECEIPTS_PER_ADDRESS + 1
        assert len(mailer.receipts) == RECEIPTS_PER_ADDRESS


class TestChatReportIntakeService:
    @staticmethod
    def _service(reports, *, mailer=None):
        return ChatReportIntakeService(
            transaction=FakeTransaction(),
            cases=FakeCases(),
            reports=reports,
            mailer=mailer or FakeMailer(),
        )

    @staticmethod
    def _take(service, reporter_id=REPORTER_ID):
        service.take(reporter_id=reporter_id, room_id="sphere:1", message_id=1)

    def test_a_new_report_opens_a_case_and_tells_staff(self):
        reports, mailer = FakeReports(_report(case_id=None)), FakeMailer()

        self._take(self._service(reports, mailer=mailer))

        assert reports.attached == {1: 101}
        assert [
            (a.case_id, a.source, a.record_id, a.category, a.urgent, a.explanation)
            for a in mailer.alerts
        ] == [(101, ModerationSource.CHAT_REPORT, 1, None, False, "Insults")]

    def test_another_report_of_the_same_message_joins_its_case_quietly(self):
        reports = FakeReports(
            _report(1, case_id=9), _report(2, case_id=None, reporter_id=5)
        )
        mailer = FakeMailer()

        self._take(self._service(reports, mailer=mailer), reporter_id=5)

        assert reports.attached == {2: 9}
        assert not mailer.alerts

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
                "suspended_until": LAST_DAY,
                "facts": " Three accounts enrolled in one seat. ",
                "from_report": False,
            }
            | overrides
        )

    @staticmethod
    def _service(*, statements=None, mailer=None, cases=None):
        return StatementOfReasonsService(
            transaction=FakeTransaction(),
            cases=cases or FakeCases(),
            statements=statements or FakeStatements(),
            mailer=mailer or FakeMailer(),
        )

    def test_records_and_mails_a_statement_under_a_new_case(self):
        statements, mailer, cases = FakeStatements(), FakeMailer(), FakeCases()

        issued = self._service(statements=statements, mailer=mailer, cases=cases).issue(
            self._statement()
        )

        assert issued == IssuedStatement(
            case_id=FIRST_CASE_ID, user_id=AUTHOR_ID, mailed=True
        )
        assert statements.created == [
            {
                "case_id": FIRST_CASE_ID,
                "user_id": AUTHOR_ID,
                "decision": ModerationDecision.ACCOUNT_SUSPENDED,
                "ground": ModerationGround.TERMS_MULTIPLE_ACCOUNTS,
                "legal_provision": "",
                "suspended_until": LAST_DAY,
                "facts": "Three accounts enrolled in one seat.",
                "from_report": False,
                "automated": False,
            }
        ]
        assert [case for __, case in mailer.statements] == [FIRST_CASE_ID]
        assert cases.closed == 1

    def test_keeps_the_case_it_was_given_and_says_when_nobody_was_reached(self):
        cases = FakeCases()

        issued = self._service(cases=cases, mailer=FakeMailer(reachable=False)).issue(
            self._statement(case_id=GIVEN_CASE_ID)
        )

        assert issued == IssuedStatement(
            case_id=GIVEN_CASE_ID, user_id=AUTHOR_ID, mailed=False
        )
        assert cases.opened == 0

    def test_a_case_explains_itself_to_one_person_once(self):
        statements, mailer = FakeStatements(), FakeMailer()
        service = self._service(statements=statements, mailer=mailer)
        service.issue(self._statement(case_id=GIVEN_CASE_ID))

        again = service.issue(self._statement(case_id=GIVEN_CASE_ID))

        assert again is None
        assert len(statements.created) == len(mailer.statements) == 1

    @pytest.mark.parametrize(
        "overrides",
        (
            {"decision": ModerationDecision.NO_ACTION},
            {"suspended_until": None},
            {"ground": ModerationGround.ILLEGAL_CONTENT, "legal_provision": " "},
        ),
        ids=["no-action", "suspension-without-end", "law-without-provision"],
    )
    def test_a_statement_missing_what_art_17_asks_for_is_refused(self, overrides):
        statements, mailer = FakeStatements(), FakeMailer()

        with pytest.raises(InvalidVerdictError):
            self._service(statements=statements, mailer=mailer).issue(
                self._statement(**overrides)
            )
        assert not statements.created
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

        result = self._service(notices=notices, mailer=mailer).decide_notices(
            notice_ids=[1], verdict=_actioned(), affected_user_id=AUTHOR_ID
        )

        assert result.decided == 1
        assert result.statements == [
            IssuedStatement(case_id=7, user_id=AUTHOR_ID, mailed=True)
        ]
        decision = notices.decisions[1]
        assert (
            decision["status"],
            decision["decision"],
            decision["ground"],
            decision["legal_provision"],
            decision["suspended_until"],
            decision["decision_text"],
        ) == (
            ModerationStatus.ACTIONED,
            ModerationDecision.CONTENT_REMOVED,
            "illegal_content",
            PROVISION,
            None,
            "The shop sold fake tickets.",
        )
        assert [
            (o.case_id, o.status, o.address, o.language, o.reporter_id)
            for o in mailer.outcomes
        ] == [(7, ModerationStatus.ACTIONED, "ola@example.com", "pl", None)]
        assert [
            (s.user_id, s.decision, s.ground, s.legal_provision, s.from_report, case)
            for s, case in mailer.statements
        ] == [
            (
                AUTHOR_ID,
                ModerationDecision.CONTENT_REMOVED,
                ModerationGround.ILLEGAL_CONTENT,
                PROVISION,
                True,
                7,
            )
        ]

    def test_a_suspension_tells_the_author_its_last_day(self):
        mailer = FakeMailer()

        self._service(notices=FakeNotices(_notice()), mailer=mailer).decide_notices(
            notice_ids=[1],
            verdict=_actioned(
                decision=ModerationDecision.ACCOUNT_SUSPENDED,
                ground=ModerationGround.TERMS_OTHERS_RIGHTS,
                legal_provision="",
                suspended_until=LAST_DAY,
            ),
            affected_user_id=AUTHOR_ID,
        )

        assert [s.suspended_until for s, __ in mailer.statements] == [LAST_DAY]

    def test_a_rejected_notice_records_no_action_and_explains_to_nobody(self):
        notices, mailer = FakeNotices(_notice()), FakeMailer()

        self._service(notices=notices, mailer=mailer).decide_notices(
            notice_ids=[1],
            verdict=_actioned(status=ModerationStatus.REJECTED, legal_provision=""),
            affected_user_id=AUTHOR_ID,
        )

        decision = notices.decisions[1]
        assert (
            decision["decision"],
            decision["ground"],
            decision["legal_provision"],
        ) == (ModerationDecision.NO_ACTION, "", "")
        assert [o.status for o in mailer.outcomes] == [ModerationStatus.REJECTED]
        assert not mailer.statements

    def test_a_closed_notice_is_left_alone_and_an_anonymous_one_mails_nobody(self):
        notices = FakeNotices(
            _notice(1, status=ModerationStatus.REJECTED),
            _notice(2, reporter_email="", case_id=None),
        )
        mailer, cases = FakeMailer(), FakeCases()

        result = self._service(
            notices=notices, mailer=mailer, cases=cases
        ).decide_notices(notice_ids=[1, 2], verdict=_actioned(), affected_user_id=None)

        assert result.decided == 1
        assert list(notices.decisions) == [2]
        assert not mailer.outcomes
        assert not mailer.statements
        assert cases.opened == 1

    def test_one_affected_account_cannot_answer_for_several_notices(self):
        notices, mailer = FakeNotices(_notice(1), _notice(2)), FakeMailer()

        with pytest.raises(InvalidVerdictError):
            self._service(notices=notices, mailer=mailer).decide_notices(
                notice_ids=[1, 2], verdict=_actioned(), affected_user_id=AUTHOR_ID
            )
        assert not notices.decisions
        assert not mailer.statements

    def test_a_chat_report_tells_its_reporter_and_explains_to_the_author(self):
        reports, mailer = FakeReports(_report()), FakeMailer()

        result = self._service(reports=reports, mailer=mailer).decide_chat_reports(
            report_ids=[1],
            verdict=_actioned(
                decision=ModerationDecision.WARNING,
                ground=ModerationGround.TERMS_OTHERS_RIGHTS,
                legal_provision="",
            ),
        )

        assert result.decided == 1
        assert [(o.case_id, o.reporter_id, o.address) for o in mailer.outcomes] == [
            (9, REPORTER_ID, "")
        ]
        assert [(s.user_id, s.decision, case) for s, case in mailer.statements] == [
            (AUTHOR_ID, ModerationDecision.WARNING, 9)
        ]

    def test_an_author_reported_by_several_people_gets_one_statement(self):
        reports = FakeReports(
            _report(1), _report(2, reporter_id=5), _report(3, reporter_id=6)
        )
        mailer = FakeMailer()

        result = self._service(reports=reports, mailer=mailer).decide_chat_reports(
            report_ids=[1, 2, 3], verdict=_actioned()
        )

        assert result.decided == len(mailer.outcomes) == 1 + 1 + 1
        assert len(result.statements) == len(mailer.statements) == 1

    def test_reports_of_one_message_under_older_separate_cases_explain_it_once(self):
        reports = FakeReports(
            _report(1, case_id=None), _report(2, case_id=8, reporter_id=5)
        )
        mailer = FakeMailer()

        result = self._service(reports=reports, mailer=mailer).decide_chat_reports(
            report_ids=[1, 2], verdict=_actioned()
        )

        assert len(mailer.outcomes) == 1 + 1
        assert len(result.statements) == len(mailer.statements) == 1

    def test_a_rejected_chat_report_tells_its_reporter_and_nobody_else(self):
        mailer = FakeMailer()

        result = self._service(
            reports=FakeReports(_report()), mailer=mailer
        ).decide_chat_reports(
            report_ids=[1], verdict=_actioned(status=ModerationStatus.REJECTED)
        )

        assert [o.status for o in mailer.outcomes] == [ModerationStatus.REJECTED]
        assert not result.statements

    def test_a_verdict_is_checked_before_anything_acts_on_it(self):
        service = self._service()

        service.check(_actioned())
        with pytest.raises(InvalidVerdictError):
            service.check(_actioned(legal_provision=""))

    def test_a_chat_report_already_closed_or_without_an_author_explains_nothing(self):
        reports = FakeReports(_report(1), _report(2, reported_user_id=None))
        reports.decisions[1] = {}
        mailer = FakeMailer()

        result = self._service(reports=reports, mailer=mailer).decide_chat_reports(
            report_ids=[1, 2], verdict=_actioned()
        )

        assert result.decided == 1
        assert [o.case_id for o in mailer.outcomes] == [9]
        assert not mailer.statements

    @pytest.mark.parametrize(
        "verdict",
        (
            _actioned(status=ModerationStatus.OPEN),
            _actioned(decision=ModerationDecision.NO_ACTION),
            _actioned(ground=None),
            _actioned(decision_text="  "),
            _actioned(legal_provision=""),
            _actioned(decision=ModerationDecision.ACCOUNT_SUSPENDED),
        ),
        ids=[
            "still-open",
            "action-without-measure",
            "action-without-ground",
            "silent",
            "law-without-provision",
            "suspension-without-end",
        ],
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
