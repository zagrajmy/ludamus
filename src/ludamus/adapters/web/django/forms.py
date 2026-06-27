from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from ludamus.adapters.db.django.models import (
    EnrollmentConfig,
    Session,
    SessionParticipation,
    SessionParticipationStatus,
    Space,
    TimeSlot,
    can_enroll_users,
    get_used_slots,
    get_vc_available_slots,
)
from ludamus.mills import get_user_enrollment_config
from ludamus.pacts import (
    EnrollmentConfigRepositoryProtocol,
    EventDTO,
    TicketAPIProtocol,
    UserData,
    UserDTO,
    UserType,
    VirtualEnrollmentConfig,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable


TODAY = datetime.now(tz=UTC).date()
logger = logging.getLogger(__name__)


class BaseUserForm(forms.Form):
    name = forms.CharField(
        label=_("User name"),
        help_text=_(
            "Your public display name that others will see. This can be a nickname "
            "and does not need to be your legal name."
        ),
    )

    @property
    def user_data(self) -> UserData:
        return cast("UserData", self.cleaned_data)


class UserForm(BaseUserForm):
    user_type = forms.CharField(initial=UserType.ACTIVE, widget=forms.HiddenInput())
    email = forms.EmailField(label=_("email address"), required=False)
    discord_username = forms.CharField(
        label=_("Discord username"),
        required=False,
        max_length=150,
        help_text=_("Your Discord username for session coordination"),
    )


class ConnectedUserForm(BaseUserForm):
    user_type = forms.CharField(
        initial=UserType.CONNECTED.value, widget=forms.HiddenInput()
    )


def _can_join_waitlist(
    *,
    user: UserDTO,
    session: Session,
    enrollment_config: EnrollmentConfig | None,
    current_user_enrollment_config: VirtualEnrollmentConfig | None,
) -> bool:
    if not enrollment_config:
        return False
    if enrollment_config.max_waitlist_sessions == 0:
        return False
    if (
        enrollment_config.restrict_to_configured_users
        and not current_user_enrollment_config
    ):
        return False

    current_waitlist_count = SessionParticipation.objects.filter(
        user_id=user.pk,
        status=SessionParticipationStatus.WAITING,
        session__event=session.event,
        session__agenda_item__isnull=False,
    ).count()
    return current_waitlist_count < enrollment_config.max_waitlist_sessions


def _build_user_choices(
    *,
    current_participation: SessionParticipation | None,
    has_conflict: bool,
    user_can_enroll: bool,
    can_join_wl: bool,
) -> tuple[list[tuple[str, str]], str]:
    choices: list[tuple[str, str]] = [("", _("No change"))]
    help_text = ""

    match current_participation and current_participation.status:
        case SessionParticipationStatus.CONFIRMED:
            choices.append(("cancel", _("Cancel enrollment")))
            if can_join_wl:
                choices.append(("waitlist", _("Move to waiting list")))
        case SessionParticipationStatus.WAITING:
            choices.append(("cancel", _("Cancel enrollment")))
            if user_can_enroll:
                choices.append(("enroll", _("Enroll (if spots available)")))
        case SessionParticipationStatus.OFFERED:
            # The seat is held for this user; claiming happens via the offer
            # link. Here they may only decline it (which frees the held seat).
            choices.append(("cancel", _("Decline offer")))
        case _:
            choices, help_text = _build_default_choices(
                user_can_enroll=user_can_enroll,
                can_join_wl=can_join_wl,
                has_conflict=has_conflict,
            )

    return choices, help_text


def _build_default_choices(
    *, user_can_enroll: bool, can_join_wl: bool, has_conflict: bool
) -> tuple[list[tuple[str, str]], str]:
    if has_conflict:
        choices: list[tuple[str, str]] = [("", _("No change (time conflict)"))]
        if can_join_wl:
            choices.append(("waitlist", _("Join waiting list")))
        return choices, _("Time conflict detected")

    choices = [("", _("No change"))]
    if user_can_enroll:
        choices.append(("enroll", _("Enroll")))
    if can_join_wl:
        choices.append(("waitlist", _("Join waiting list")))
    return choices, ""


def _has_no_actionable_choices(choices: list[tuple[str, str]]) -> bool:
    return len(choices) == 0 or (len(choices) == 1 and not choices[0][0])


def _build_fallback_choices(
    *,
    enrollment_config: EnrollmentConfig | None,
    current_user_enrollment_config: VirtualEnrollmentConfig | None,
    user: UserDTO,
) -> tuple[list[tuple[str, str]], str]:
    if enrollment_config and enrollment_config.restrict_to_configured_users:
        if not user.email:
            return (
                [("", _("No enrollment options (email required)"))],
                _("Email address required for enrollment"),
            )
        if not current_user_enrollment_config:
            return (
                [("", _("No enrollment options (access required)"))],
                _("Enrollment access permission required"),
            )
    return [("", _("No change"))], _("No enrollment options available")


class _UserEnrollmentChoiceField(forms.ChoiceField):
    def __init__(
        self,
        *,
        user_obj: UserDTO,
        enrollment_config: EnrollmentConfig | None,
        current_user_enrollment_config: VirtualEnrollmentConfig | None,
        user_can_enroll: bool,
        current_user: UserDTO,
        **kwargs: Any,
    ) -> None:
        self.user_obj = user_obj
        self._enrollment_config = enrollment_config
        self._current_user_enrollment_config = current_user_enrollment_config
        self._user_can_enroll = user_can_enroll
        self._current_user = current_user
        super().__init__(**kwargs)

    def validate(self, value: str) -> None:
        if value and value not in [choice[0] for choice in self.choices]:  # type: ignore [index, union-attr]
            user_name = self.user_obj.name or _("User")
            self._validate_rejected_value(value, user_name)
        super().validate(value)

    def _validate_rejected_value(self, value: str, user_name: str) -> None:
        if value == "enroll":
            self._raise_enroll_error(user_name)
        elif value != "waitlist":
            raise ValidationError(
                _("Invalid choice for %(user)s: %(value)s")
                % {"user": user_name, "value": value}
            )

    def _raise_enroll_error(self, user_name: str) -> None:
        ec = self._enrollment_config
        if ec and ec.restrict_to_configured_users:
            if not self._current_user.email:
                raise ValidationError(
                    _("%(user)s cannot enroll: email address required")
                    % {"user": user_name}
                )
            if not self._current_user_enrollment_config:
                raise ValidationError(
                    _("%(user)s cannot enroll: enrollment access permission required")
                    % {"user": user_name}
                )
        elif not self._user_can_enroll:
            raise ValidationError(
                _("%(user)s cannot enroll: enrollment not available")
                % {"user": user_name}
            )


def _make_enrollment_clean(
    *,
    current_user: UserDTO,
    connected_users: Iterable[UserDTO],
    enrollment_config: EnrollmentConfig | None,
    current_user_enrollment_config: VirtualEnrollmentConfig | None,
    field_to_user_name: dict[str, str],
) -> Callable[..., dict[str, Any] | None]:
    all_users = [current_user, *connected_users]

    def clean(self: forms.Form) -> dict[str, Any] | None:
        if not (cleaned_data := forms.Form.clean(self)):
            return cleaned_data

        enroll_requests = [
            user
            for field_name, value in cleaned_data.items()
            if field_name.startswith("user_") and value == "enroll"
            for user in all_users
            if user.pk == int(field_name.split("_")[1])
        ]

        if (
            enroll_requests
            and enrollment_config
            and enrollment_config.restrict_to_configured_users
            and current_user_enrollment_config
            and not can_enroll_users(
                users=all_users,
                event=EventDTO.model_validate(enrollment_config.event),
                virtual_config=current_user_enrollment_config,
                users_to_enroll=enroll_requests,
            )
        ):
            event = EventDTO.model_validate(enrollment_config.event)
            used_slots = get_used_slots(users=all_users, event=event)
            available_slots = get_vc_available_slots(
                users=all_users,
                event=event,
                virtual_config=current_user_enrollment_config,
            )
            user_field = next(
                field_name
                for field_name, value in cleaned_data.items()
                if field_name.startswith("user_") and value == "enroll"
            )
            user_name = field_to_user_name.get(user_field, "User")
            self.add_error(
                user_field,
                (
                    f"{user_name}: Cannot enroll more users. You have "
                    f"already enrolled {used_slots} out of "
                    f"{current_user_enrollment_config.allowed_slots} "
                    "unique people "
                    "(each person can enroll in multiple sessions). "
                    f"Only {available_slots} slots remaining for "
                    "new people."
                ),
            )

        return cleaned_data

    return clean


def create_enrollment_form(
    *,
    session: Session,
    current_user: UserDTO,
    connected_users: Iterable[UserDTO],
    enrollment_config_repo: EnrollmentConfigRepositoryProtocol,
    ticket_api: TicketAPIProtocol,
) -> type[forms.Form]:
    enrollment_config = session.event.get_most_liberal_config(session)
    current_user_enrollment_config = get_user_enrollment_config(
        event=EventDTO.model_validate(session.event),
        user_email=current_user.email,
        enrollment_config_repo=enrollment_config_repo,
        ticket_api=ticket_api,
        check_interval_minutes=settings.MEMBERSHIP_API_CHECK_INTERVAL,
    )
    user_can_enroll = bool(
        enrollment_config
        and (
            not enrollment_config.restrict_to_configured_users
            or (
                current_user_enrollment_config
                and current_user_enrollment_config.allowed_slots
            )
        )
    )

    form_fields: dict[str, _UserEnrollmentChoiceField] = {}
    field_to_user_name: dict[str, str] = {}

    for user in (current_user, *connected_users):
        current_participation = SessionParticipation.objects.filter(
            session=session, user_id=user.pk
        ).first()
        has_conflict = Session.objects.has_conflicts(session, user)
        can_join_wl = _can_join_waitlist(
            user=user,
            session=session,
            enrollment_config=enrollment_config,
            current_user_enrollment_config=current_user_enrollment_config,
        )

        choices, help_text = _build_user_choices(
            current_participation=current_participation,
            has_conflict=has_conflict,
            user_can_enroll=user_can_enroll,
            can_join_wl=can_join_wl,
        )
        if _has_no_actionable_choices(choices) and not has_conflict:
            choices, help_text = _build_fallback_choices(
                enrollment_config=enrollment_config,
                current_user_enrollment_config=current_user_enrollment_config,
                user=user,
            )

        field_name = f"user_{user.pk}"
        field_to_user_name[field_name] = user.full_name
        form_fields[field_name] = _UserEnrollmentChoiceField(
            user_obj=user,
            enrollment_config=enrollment_config,
            current_user_enrollment_config=current_user_enrollment_config,
            user_can_enroll=user_can_enroll,
            current_user=current_user,
            choices=choices,
            required=False,
            label=user.full_name,
            help_text=help_text,
            widget=forms.Select(
                attrs={
                    "class": "form-select",
                    "data-user-id": user.pk,
                    "disabled": None,
                }
            ),
        )

    clean = _make_enrollment_clean(
        current_user=current_user,
        connected_users=connected_users,
        enrollment_config=enrollment_config,
        current_user_enrollment_config=current_user_enrollment_config,
        field_to_user_name=field_to_user_name,
    )

    form = type("EnrollmentForm", (forms.Form,), form_fields)
    form.clean = clean  # type: ignore [attr-defined]
    return form


def create_proposal_acceptance_form(event: EventDTO) -> type[forms.Form]:
    # Query spaces with related area and venue for proper grouping
    spaces = (
        Space.objects.filter(event_id=event.pk)
        .select_related("area__venue")
        .order_by(*Space.HIERARCHICAL_ORDER)
    )

    # Build grouped choices: {(venue_name, area_name): [(space_id, space_name), ...]}
    grouped_choices: dict[str, list[tuple[int, str]]] = {}
    for space in spaces:
        group_label = f"{space.area.venue.name} > {space.area.name}"
        if group_label not in grouped_choices:
            grouped_choices[group_label] = []
        grouped_choices[group_label].append((space.id, space.name))

    # Convert to choices format with optgroups
    choices: list[tuple[str, str] | tuple[str, list[tuple[int, str]]]] = [
        ("", _("Select a space..."))
    ]
    choices.extend(list(grouped_choices.items()))

    space_field = forms.ChoiceField(
        choices=choices,
        label=_("Space"),
        widget=forms.Select(attrs={"class": "form-select"}),
        help_text=_("Select the space where this session will take place"),
        required=True,
    )

    time_slot_field = forms.ModelChoiceField(
        queryset=TimeSlot.objects.filter(event_id=event.pk).order_by("start_time"),
        label=_("Time slot"),
        widget=forms.Select(attrs={"class": "form-select"}),
        help_text=_("Select the time slot for this session"),
        empty_label=_("Select a time slot..."),
        required=True,
    )

    def clean_space(self: forms.Form) -> Space:
        if not (space_id := self.cleaned_data.get("space")):  # pragma: no cover
            raise ValidationError(_("This field is required."))
        try:
            return Space.objects.get(pk=int(space_id), event_id=event.pk)
        except (Space.DoesNotExist, ValueError) as e:
            raise ValidationError(_("Invalid space selection.")) from e

    def clean(self: forms.Form) -> dict[str, Any] | None:
        if (cleaned_data := super(forms.Form, self).clean()) and Session.objects.filter(
            agenda_item__space=cleaned_data.get("space"),
            agenda_item__start_time=cleaned_data["time_slot"].start_time,
            agenda_item__end_time=cleaned_data["time_slot"].end_time,
        ).exists():
            raise ValidationError(
                _("There is already a session scheduled at this space and time.")
            )
        return cleaned_data

    form_attrs = {
        "space": space_field,
        "time_slot": time_slot_field,
        "clean_space": clean_space,
        "clean": clean,
    }

    return type("ProposalAcceptanceForm", (forms.Form,), form_attrs)
