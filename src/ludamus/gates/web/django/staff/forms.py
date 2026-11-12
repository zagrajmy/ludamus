from __future__ import annotations

from typing import TYPE_CHECKING

from django import forms
from django.utils.translation import gettext_lazy as _

from ludamus.pacts.staff_cases import (
    STAFF_REPLY_MAX_LENGTH,
    ModerationAction,
    ModerationGround,
    StaffCaseKind,
)

if TYPE_CHECKING:
    from django.http import QueryDict
    from django.utils.functional import _StrPromise

    from ludamus.pacts.staff_cases import StaffMemberDTO

KIND_LABELS: dict[StaffCaseKind, _StrPromise] = {
    StaffCaseKind.CHAT_REPORT: _("Chat report"),
    StaffCaseKind.NOTICE: _("Notice form"),
    StaffCaseKind.APPEAL: _("Appeal"),
    StaffCaseKind.EMAIL: _("Email"),
}
ACTION_LABELS: dict[ModerationAction, _StrPromise] = {
    ModerationAction.NONE: _("No action"),
    ModerationAction.HIDE: _("Hide content"),
    ModerationAction.REMOVE: _("Remove content"),
    ModerationAction.MUTE_24H: _("Mute for 24 hours"),
    ModerationAction.SUSPEND: _("Suspend account"),
}
GROUND_LABELS: dict[ModerationGround, _StrPromise] = {
    ModerationGround.DISRUPTION: _("Terms § 4.1 point 4: disrupting the service"),
    ModerationGround.MISUSE: _(
        "Terms § 4.1 point 5: using the service against its purpose"
    ),
    ModerationGround.RIGHTS: _("Terms § 4.1 point 6: violating other users' rights"),
    ModerationGround.UNLAWFUL_OR_INDECENT: _(
        "Terms § 4.1 point 7: unlawful or indecent content"
    ),
    ModerationGround.ILLEGAL: _("Illegal content"),
}


class ReplyForm(forms.Form):
    body = forms.CharField(
        label=_("Reply as the staff address"),
        max_length=STAFF_REPLY_MAX_LENGTH,
        widget=forms.Textarea(attrs={"rows": 4}),
    )


class AssignForm(forms.Form):
    assignee = forms.TypedChoiceField(
        label=_("Handled by"), coerce=int, empty_value=None, required=False
    )

    def __init__(
        self,
        data: QueryDict | None = None,
        *,
        staff: list[StaffMemberDTO],
        assignee_id: int | None = None,
    ) -> None:
        super().__init__(data, initial={"assignee": assignee_id})
        field = self.fields["assignee"]
        if isinstance(field, forms.TypedChoiceField):
            field.choices = [
                ("", _("Nobody")),
                *((member.pk, member.name) for member in staff),
            ]


class DecisionForm(forms.Form):
    action = forms.ChoiceField(
        label=_("Action"),
        choices=list(ACTION_LABELS.items()),
        widget=forms.RadioSelect,
        initial=ModerationAction.HIDE,
    )
    ground = forms.ChoiceField(
        label=_("Ground"),
        choices=list(GROUND_LABELS.items()),
        initial=ModerationGround.UNLAWFUL_OR_INDECENT,
    )
