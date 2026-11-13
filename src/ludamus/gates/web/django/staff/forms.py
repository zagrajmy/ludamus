from __future__ import annotations

from typing import TYPE_CHECKING

from django import forms
from django.utils.translation import gettext_lazy as _

from ludamus.pacts.moderation import (
    DECISION_TEXT_MAX_LENGTH,
    LEGAL_PROVISION_MAX_LENGTH,
    ModerationDecision,
    ModerationGround,
)
from ludamus.pacts.staff_cases import STAFF_REPLY_MAX_LENGTH, CaseKind, StaffDecision

if TYPE_CHECKING:
    from django.http import QueryDict
    from django.utils.functional import _StrPromise

    from ludamus.pacts.staff_cases import StaffMemberDTO

KIND_LABELS: dict[CaseKind, _StrPromise] = {
    CaseKind.NOTICE: _("Notice form"),
    CaseKind.CHAT_REPORT: _("Chat report"),
    CaseKind.EMAIL: _("Email"),
    CaseKind.STATEMENT: _("Own decision"),
}
DECISION_LABELS: dict[ModerationDecision, _StrPromise] = {
    ModerationDecision.NO_ACTION: _("No action"),
    ModerationDecision.WARNING: _("Warning"),
    ModerationDecision.CONTENT_REMOVED: _("Remove content"),
    ModerationDecision.ACCOUNT_SUSPENDED: _("Suspend account"),
    ModerationDecision.ACCOUNT_REMOVED: _("Remove account"),
}
GROUND_LABELS: dict[ModerationGround, _StrPromise] = {
    ModerationGround.TERMS_FALSE_DATA: _("Terms § 4.1 point 1: false information"),
    ModerationGround.TERMS_MULTIPLE_ACCOUNTS: _(
        "Terms § 4.1 point 2: more than one account"
    ),
    ModerationGround.TERMS_FAKE_SIGNUPS: _(
        "Terms § 4.1 point 3: enrolling with no intention to attend"
    ),
    ModerationGround.TERMS_DISRUPTION: _("Terms § 4.1 point 4: disrupting the service"),
    ModerationGround.TERMS_MISUSE: _(
        "Terms § 4.1 point 5: using the service against its purpose"
    ),
    ModerationGround.TERMS_OTHERS_RIGHTS: _(
        "Terms § 4.1 point 6: violating other users' rights"
    ),
    ModerationGround.TERMS_UNLAWFUL_CONTENT: _(
        "Terms § 4.1 point 7: unlawful or indecent content"
    ),
    ModerationGround.TERMS_UNAUTHORISED_ACCESS: _(
        "Terms § 4.1 point 8: reaching other users' data without permission"
    ),
    ModerationGround.ILLEGAL_CONTENT: _("Illegal content"),
}


class ReplyForm(forms.Form):
    body = forms.CharField(
        label=_("Reply as the staff address"),
        max_length=STAFF_REPLY_MAX_LENGTH,
        widget=forms.Textarea(attrs={"rows": 4}),
    )


class AssignForm(forms.Form):
    def __init__(
        self,
        data: QueryDict | None = None,
        *,
        staff: list[StaffMemberDTO],
        assignee_id: int | None = None,
    ) -> None:
        super().__init__(data, initial={"assignee": assignee_id})
        self.fields["assignee"] = forms.TypedChoiceField(
            label=_("Handled by"),
            coerce=int,
            empty_value=None,
            required=False,
            choices=[
                ("", _("Nobody")),
                *((member.pk, member.name) for member in staff),
            ],
        )


class DecisionForm(forms.Form):
    decision = forms.ChoiceField(
        label=_("Decision"),
        choices=list(DECISION_LABELS.items()),
        widget=forms.RadioSelect,
        initial=ModerationDecision.CONTENT_REMOVED,
    )
    ground = forms.ChoiceField(
        label=_("Ground"),
        choices=[("", _("None: no action")), *GROUND_LABELS.items()],
        initial=ModerationGround.TERMS_UNLAWFUL_CONTENT,
        required=False,
    )
    legal_provision = forms.CharField(
        label=_("Provision of law"),
        help_text=_("With illegal content as the ground, e.g. art. 190 § 1 k.k."),
        max_length=LEGAL_PROVISION_MAX_LENGTH,
        required=False,
    )
    suspended_until = forms.DateField(
        label=_("Suspended until"),
        help_text=_("For a suspension: its last day."),
        widget=forms.DateInput(attrs={"type": "date"}),
        required=False,
    )
    decision_text = forms.CharField(
        label=_("Decision text"),
        help_text=_(
            "The reporter and the person affected both read it. Give the facts;"
            " never name the reporter."
        ),
        max_length=DECISION_TEXT_MAX_LENGTH,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    affected_account = forms.CharField(
        label=_("Account affected"),
        help_text=_(
            "Username, slug or email of the account whose content this is; it"
            " gets the statement of reasons."
        ),
        max_length=255,
        required=False,
    )

    def staff_decision(self) -> StaffDecision:
        """Read the decision as far as it is filled in; whole once valid."""
        data = self.cleaned_data
        return StaffDecision(
            decision=ModerationDecision(
                data.get("decision", ModerationDecision.CONTENT_REMOVED)
            ),
            ground=ModerationGround(ground) if (ground := data.get("ground")) else None,
            decision_text=data.get("decision_text", ""),
            legal_provision=data.get("legal_provision", ""),
            suspended_until=data.get("suspended_until"),
            affected_account=data.get("affected_account", ""),
        )
