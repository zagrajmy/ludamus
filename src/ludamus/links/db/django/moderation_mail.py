"""Mail about moderation: staff alerts, receipts, outcomes, statements of reasons.

Staff answers from the case inbox go out as their author wrote them, from
the staff address, with the case reference in the subject.

Every subject starts with the case reference and every message asks for
replies at the staff address, so an answer lands beside the case it is about.
A reporter who sent a notice without an account is answered at the address
they gave, in the language they wrote in; an account, in its own.
"""

from __future__ import annotations

import logging
from email.utils import parseaddr
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import translation
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from ludamus.links.absolute_url import absolute_url
from ludamus.links.db.django.delivery import compose_as_written, compose_mail, send
from ludamus.links.db.django.models import User
from ludamus.links.db.django.recipients import Voice, speaking_to
from ludamus.pacts.moderation import (
    ModerationDecision,
    ModerationGround,
    ModerationMailerProtocol,
    ModerationSource,
    ModerationStatus,
    NoticeCategory,
    StatementOfReasons,
    case_reference,
)
from ludamus.pacts.staff_cases import StaffCaseMailerProtocol

if TYPE_CHECKING:
    from ludamus.links.db.django.delivery import Mail
    from ludamus.links.db.django.recipients import Recipient
    from ludamus.pacts.moderation import (
        ModerationVerdict,
        NoticeReceipt,
        ReporterOutcome,
        StaffAlert,
    )

logger = logging.getLogger(__name__)

_UKE_URL = "https://www.uke.gov.pl/"
_ADMIN_CHANGE_URLS = {
    ModerationSource.NOTICE: "admin:db_main_contentnotice_change",
    ModerationSource.CHAT_REPORT: "admin:db_main_parleyreport_change",
}


def category_label(category: NoticeCategory) -> str:
    return {
        NoticeCategory.CHILD_SEXUAL_ABUSE: _("Child sexual abuse material"),
        NoticeCategory.CHILD_SAFETY: _("Grooming or other danger to a child"),
        NoticeCategory.THREATS_OR_HATE: _("Threats, incitement to violence or hate"),
        NoticeCategory.HARASSMENT: _("Harassment, stalking or defamation"),
        NoticeCategory.PRIVACY: _(
            "Someone's personal data or image shared without consent"
        ),
        NoticeCategory.INTELLECTUAL_PROPERTY: _("Copyright or trademark infringement"),
        NoticeCategory.FRAUD: _("Fraud, scam or phishing"),
        NoticeCategory.OTHER: _("Other illegal content"),
    }[category]


def _decision_label(decision: ModerationDecision) -> str:
    return {
        ModerationDecision.NO_ACTION: _("no action"),
        ModerationDecision.WARNING: _("a warning"),
        ModerationDecision.CONTENT_REMOVED: _("removal of your content"),
        ModerationDecision.ACCOUNT_SUSPENDED: _("suspension of your account"),
        ModerationDecision.ACCOUNT_REMOVED: _("removal of your account"),
    }[decision]


def _ground_label(ground: ModerationGround) -> str:
    return {
        ModerationGround.ILLEGAL_CONTENT: _(
            "the content is illegal under Polish or European Union law"
        ),
        ModerationGround.TERMS_FALSE_DATA: _(
            "§ 4.1(1) of the Terms of Service: giving false information"
        ),
        ModerationGround.TERMS_MULTIPLE_ACCOUNTS: _(
            "§ 4.1(2) of the Terms of Service: creating more than one account"
        ),
        ModerationGround.TERMS_FAKE_SIGNUPS: _(
            "§ 4.1(3) of the Terms of Service: enrolling with no intention to attend"
        ),
        ModerationGround.TERMS_DISRUPTION: _(
            "§ 4.1(4) of the Terms of Service: disrupting the service"
        ),
        ModerationGround.TERMS_MISUSE: _(
            "§ 4.1(5) of the Terms of Service: using the service against its purpose"
        ),
        ModerationGround.TERMS_OTHERS_RIGHTS: _(
            "§ 4.1(6) of the Terms of Service: violating other users' rights"
        ),
        ModerationGround.TERMS_UNLAWFUL_CONTENT: _(
            "§ 4.1(7) of the Terms of Service: posting content that is unlawful"
            " or offends common decency"
        ),
        ModerationGround.TERMS_UNAUTHORISED_ACCESS: _(
            "§ 4.1(8) of the Terms of Service: trying to reach other users' data"
            " without permission"
        ),
    }[ground]


def _subject(case_id: int, title: str) -> str:
    return f"[{case_reference(case_id)}] {title}"


def _redress() -> str:
    return _(
        "If you disagree, reply to this email or write to %(contact)s and a person"
        " will look at it again. You can also take the matter to a Polish court,"
        " or complain to the Office of Electronic Communications (UKE), Poland's"
        " Digital Services Coordinator: %(uke_url)s"
    ) % {"contact": settings.STAFF_EMAIL, "uke_url": _UKE_URL}


def _compose(speaker: Voice | Recipient, *, subject: str, body: str) -> Mail:
    return compose_mail(
        speaker, subject=subject, body=body, headers={"Reply-To": settings.STAFF_EMAIL}
    )


def _send_after_commit(message: Mail, *, case_id: int, kind: str) -> None:
    def _send() -> None:
        if send(message):
            logger.info(
                "Moderation mail sent",
                extra={"case": case_reference(case_id), "kind": kind},
            )

    transaction.on_commit(_send, robust=True)


def _outcome_mail(speaker: Voice | Recipient, outcome: ReporterOutcome) -> Mail:
    reference = case_reference(outcome.case_id)
    verdict = (
        _("We reviewed your report %(reference)s and acted on the content.")
        if outcome.status == ModerationStatus.ACTIONED
        else _(
            "We reviewed your report %(reference)s and decided not to act on"
            " the content."
        )
    ) % {"reference": reference}
    body = "\n\n".join(
        (verdict, _("Why:\n%(text)s") % {"text": outcome.decision_text}, _redress())
    )
    return _compose(
        speaker,
        subject=_subject(outcome.case_id, _("Decision on your report")),
        body=body,
    )


def _statement_body(statement: StatementOfReasons) -> str:
    decision = _decision_label(statement.decision)
    if statement.suspended_until is not None:
        decision = _("%(decision)s until %(date)s") % {
            "decision": decision,
            "date": date_format(statement.suspended_until, "DATE_FORMAT"),
        }
    ground = _ground_label(statement.ground)
    if statement.legal_provision:
        ground = _("%(ground)s, under %(provision)s") % {
            "ground": ground,
            "provision": statement.legal_provision,
        }
    terms_url = absolute_url(reverse("terms-of-service"), domain=settings.ROOT_DOMAIN)
    return "\n\n".join(
        (
            _("Zagrajmy staff decided on %(decision)s.") % {"decision": decision},
            _("What happened:\n%(facts)s") % {"facts": statement.facts},
            (
                _("This decision followed a report from someone else.")
                if statement.from_report
                else _("We took this decision on our own initiative.")
            ),
            (
                _(
                    "Automated means were used to find the content or reach"
                    " this decision."
                )
                if statement.automated
                else _(
                    "No automated means were used to find the content or reach"
                    " this decision."
                )
            ),
            _("Ground: %(ground)s. Terms of Service: %(url)s") % {
                "ground": ground,
                "url": terms_url,
            },
            _redress(),
        )
    )


def staff_message_id(nonce: str) -> str:
    domain = parseaddr(settings.STAFF_EMAIL)[1].rpartition("@")[2] or "localhost"
    return f"<case-{nonce}@{domain}>"


class DjangoModerationMailer(ModerationMailerProtocol, StaffCaseMailerProtocol):
    @staticmethod
    def alert_staff(alert: StaffAlert) -> None:
        admin_url = absolute_url(
            reverse(_ADMIN_CHANGE_URLS[alert.source], args=[alert.record_id]),
            domain=settings.ROOT_DOMAIN,
        )
        with Voice(settings.LANGUAGE_CODE, address=settings.STAFF_EMAIL) as voice:
            if alert.category is None:
                title = _("New chat report")
                facts = [_("Chat room: %(room)s") % {"room": alert.location}]
            else:
                title = _("New notice of illegal content: %(category)s") % {
                    "category": category_label(alert.category)
                }
                facts = [_("Content: %(url)s") % {"url": alert.location}]
            subject = _subject(alert.case_id, title)
            if alert.urgent:
                subject = _("[CHILD SAFETY] %(subject)s") % {"subject": subject}
                facts.append(
                    _(
                        "Read it first. Child sexual abuse material and suspected"
                        " abuse also go to Dyżurnet.pl or the police."
                    )
                )
            if alert.explanation:
                facts.append(_("Explanation:\n%(text)s") % {"text": alert.explanation})
            facts.append(_("Decide in the admin: %(url)s") % {"url": admin_url})
            message = _compose(voice, subject=subject, body="\n\n".join(facts))
        _send_after_commit(message, case_id=alert.case_id, kind="staff_alert")

    @staticmethod
    def send_receipt(receipt: NoticeReceipt) -> None:
        with Voice(receipt.language, address=receipt.address) as voice:
            body = "\n\n".join(
                (
                    _(
                        "Thank you. We received your report of content that may be"
                        " illegal (%(category)s). Its reference is %(reference)s."
                    )
                    % {
                        "category": category_label(receipt.category),
                        "reference": case_reference(receipt.case_id),
                    },
                    _(
                        "Zagrajmy staff will review it and write to you with the"
                        " decision. To add anything, reply to this email."
                    ),
                )
            )
            message = _compose(
                voice,
                subject=_subject(receipt.case_id, _("We received your report")),
                body=body,
            )
        _send_after_commit(message, case_id=receipt.case_id, kind="receipt")

    @staticmethod
    def send_outcome(outcome: ReporterOutcome) -> None:
        if outcome.reporter_id is None:
            with Voice(outcome.language, address=outcome.address) as voice:
                message = _outcome_mail(voice, outcome)
        else:
            with speaking_to(outcome.reporter_id) as recipient:
                if not recipient.can_mail:
                    logger.info(
                        "Report outcome not mailed: no deliverable address",
                        extra={"case": case_reference(outcome.case_id)},
                    )
                    return
                message = _outcome_mail(recipient, outcome)
        _send_after_commit(message, case_id=outcome.case_id, kind="outcome")

    @staticmethod
    def send_statement(*, statement: StatementOfReasons, case_id: int) -> bool:
        # NOTE: Art. 17 asks for the statement wherever we can reach the
        # person, so it goes to the address on record, proven or not.
        on_record = (
            User.objects.filter(pk=statement.user_id)
            .values_list("email", flat=True)
            .first()
        )
        with speaking_to(statement.user_id, mail_to=on_record or "") as recipient:
            if not recipient.can_mail:
                logger.warning(
                    "Statement of reasons not mailed: no address on record",
                    extra={
                        "case": case_reference(case_id),
                        "user_id": statement.user_id,
                    },
                )
                return False
            message = _compose(
                recipient,
                subject=_subject(
                    case_id, _("A moderation decision about your account")
                ),
                body=_statement_body(statement),
            )
        _send_after_commit(message, case_id=case_id, kind="statement_of_reasons")
        return True

    @staticmethod
    def verdict_text(verdict: ModerationVerdict) -> str:
        if verdict.ground is None:
            return ""
        return _statement_body(
            StatementOfReasons(
                user_id=0,
                case_id=None,
                decision=verdict.decision,
                ground=verdict.ground,
                facts=verdict.decision_text,
                from_report=True,
                legal_provision=verdict.legal_provision,
                suspended_until=verdict.suspended_until,
            )
        )

    @staticmethod
    def reply_subject(case_id: int) -> str:
        with translation.override(settings.LANGUAGE_CODE):
            return _subject(case_id, _("Reply from Zagrajmy staff"))

    @staticmethod
    def send_reply(*, to: str, subject: str, body: str, nonce: str) -> None:
        message = compose_as_written(
            to=to,
            subject=subject,
            body=body,
            from_email=settings.STAFF_EMAIL,
            message_id=staff_message_id(nonce),
        )

        def _send() -> None:
            if send(message):
                logger.info("Staff reply mailed", extra={"nonce": nonce})

        transaction.on_commit(_send, robust=True)
