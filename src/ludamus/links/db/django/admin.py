from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar, Protocol, override

from django import forms
from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q
from django.shortcuts import render

from ludamus.links.db.django.delivery import Bell, ring_as_written
from ludamus.links.db.django.models import (
    MODERATION_GROUND_CHOICES,
    AgendaItem,
    ContentNotice,
    DomainEnrollmentConfig,
    Encounter,
    EncounterRSVP,
    EnrollmentConfig,
    Event,
    EventProposalSettings,
    Facilitator,
    ParleyReport,
    ProposalCategory,
    Session,
    SessionFieldValue,
    Space,
    Sphere,
    SphereMembership,
    StatementOfReasons,
    Tag,
    TagCategory,
    User,
    UserEnrollmentConfig,
)
from ludamus.pacts.moderation import (
    DECISION_TEXT_MAX_LENGTH,
    LEGAL_PROVISION_MAX_LENGTH,
    InvalidVerdictError,
    ModerationDecision,
    ModerationDecisionsDTO,
    ModerationGround,
    ModerationStatus,
    ModerationVerdict,
)
from ludamus.pacts.moderation import StatementOfReasons as StatementOfReasonsData
from ludamus.pacts.notifications import NotificationKind

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from django.contrib.admin import AdminSite
    from django.db.models import Model, QuerySet
    from django.http import HttpRequest, HttpResponse

    from ludamus.pacts.services import ServicesProtocol


class _Wiring:
    def __init__(self) -> None:
        self.services: Callable[[], ServicesProtocol] | None = None


_wiring = _Wiring()


def register(*, make_services: Callable[[], ServicesProtocol]) -> None:
    """Hand over what admin actions run: Django builds the admin itself."""
    _wiring.services = make_services


def _services() -> ServicesProtocol:
    if _wiring.services is None:
        msg = "No services registered for the admin."
        raise ImproperlyConfigured(msg)
    return _wiring.services()


_ACTION_DECISIONS = [
    (decision.value, decision.name.replace("_", " ").capitalize())
    for decision in ModerationDecision
    if decision != ModerationDecision.NO_ACTION
]
_DECISION_TEXT_HELP = (
    "Sent to the reporter and to the person affected. Give the facts; never"
    " name the reporter."
)


class _StatementTermsForm(forms.Form):
    legal_provision = forms.CharField(
        max_length=LEGAL_PROVISION_MAX_LENGTH,
        required=False,
        help_text=(
            "Required when the ground is the law: the provision broken, e.g."
            " art. 286 § 1 Kodeksu karnego."
        ),
    )
    suspended_until = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Required for a suspension: its last day.",
    )


class StatementForm(_StatementTermsForm):
    decision = forms.ChoiceField(choices=_ACTION_DECISIONS)
    ground = forms.ChoiceField(choices=MODERATION_GROUND_CHOICES)
    field_order = ("decision", "ground", "legal_provision", "suspended_until")
    facts = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 5}),
        max_length=DECISION_TEXT_MAX_LENGTH,
        help_text="What was done and why, as the person will read it.",
    )


class VerdictForm(_StatementTermsForm):
    field_order = ("status", "decision", "ground", "legal_provision", "suspended_until")
    status = forms.ChoiceField(
        choices=[
            (ModerationStatus.ACTIONED.value, "Actioned: we acted on the content"),
            (ModerationStatus.REJECTED.value, "Rejected: no action"),
        ],
        widget=forms.RadioSelect,
    )
    decision = forms.ChoiceField(
        choices=[("", "---------"), *_ACTION_DECISIONS],
        required=False,
        help_text="For an actioned report: what was done.",
    )
    ground = forms.ChoiceField(
        choices=[("", "---------"), *MODERATION_GROUND_CHOICES],
        required=False,
        help_text="For an actioned report: the law, or the point of § 4.1 broken.",
    )
    decision_text = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 5}),
        max_length=DECISION_TEXT_MAX_LENGTH,
        help_text=_DECISION_TEXT_HELP,
    )

    def verdict(self) -> ModerationVerdict:
        data = self.cleaned_data
        return ModerationVerdict(
            status=ModerationStatus(data["status"]),
            decision=ModerationDecision(
                data["decision"] or ModerationDecision.NO_ACTION
            ),
            ground=ModerationGround(data["ground"]) if data["ground"] else None,
            legal_provision=data["legal_provision"],
            suspended_until=data["suspended_until"],
            decision_text=data["decision_text"],
        )


class NoticeVerdictForm(VerdictForm):
    affected_account = forms.CharField(
        required=False,
        help_text=(
            "Username or email of the account whose content this is. With an"
            " actioned report, they get a statement of reasons."
        ),
    )

    def clean_affected_account(self) -> int | None:
        if not (identifier := self.cleaned_data["affected_account"].strip()):
            return None
        matches = list(
            User.objects.filter(
                Q(username=identifier)
                | Q(email__iexact=identifier)
                | Q(slug=identifier)
            ).values_list("pk", flat=True)[:2]
        )
        if not matches:
            msg = "No account by that username or email."
            raise forms.ValidationError(msg)
        if len(matches) > 1:
            msg = "Several accounts match; give the username."
            raise forms.ValidationError(msg)
        return matches[0]


class _ActionAdmin(Protocol):
    admin_site: AdminSite

    def message_user(
        self, request: HttpRequest, message: str, level: int = ...
    ) -> None: ...


@dataclass(frozen=True, kw_only=True)
class _ActionCopy:
    action: str
    lead: str
    consequence: str
    submit_label: str


def _action_page(
    request: HttpRequest,
    *,
    modeladmin: _ActionAdmin,
    form: forms.Form,
    items: QuerySet[Model],
    copy: _ActionCopy,
) -> HttpResponse:
    return render(
        request,
        "admin/moderation_action.html",
        {
            **modeladmin.admin_site.each_context(request),
            "title": copy.submit_label,
            "form": form,
            "items": items,
            "action": copy.action,
            "lead": copy.lead,
            "consequence": copy.consequence,
            "submit_label": copy.submit_label,
            "action_checkbox_name": helpers.ACTION_CHECKBOX_NAME,
        },
    )


def _report_statements(
    modeladmin: _ActionAdmin, request: HttpRequest, result: ModerationDecisionsDTO
) -> None:
    if mailed := sum(statement.mailed for statement in result.statements):
        modeladmin.message_user(
            request, f"Statement of reasons mailed to {mailed} user(s)."
        )
    if unreached := [s.user_id for s in result.statements if not s.mailed]:
        names = ", ".join(
            user.name or user.username
            for user in User.objects.filter(pk__in=unreached).order_by("pk")
        )
        modeladmin.message_user(
            request,
            f"No address on record for {names}: reach them another way.",
            messages.WARNING,
        )


_REPORT_CONSEQUENCE = (
    "Closing mails the reporter the outcome and how to challenge it. An"
    " actioned report also sends the person affected a statement of reasons."
)


@admin.action(description="Decide on selected notices")
def decide_notices(
    modeladmin: _ActionAdmin, request: HttpRequest, queryset: QuerySet[ContentNotice]
) -> HttpResponse | None:
    form = NoticeVerdictForm(request.POST if "apply" in request.POST else None)
    if form.is_valid():
        verdict = form.verdict()
        affected = form.cleaned_data["affected_account"]
        try:
            result = _services().moderation_decisions.decide_notices(
                notice_ids=list(queryset.values_list("pk", flat=True)),
                verdict=verdict,
                affected_user_id=affected,
            )
        except InvalidVerdictError as error:
            form.add_error(None, str(error))
        else:
            modeladmin.message_user(request, f"Decided {result.decided} notice(s).")
            _report_statements(modeladmin, request, result)
            if verdict.status == ModerationStatus.ACTIONED and affected is None:
                modeladmin.message_user(
                    request,
                    "No statement of reasons went out: no affected account was"
                    " named. Send one from Users if someone's content was acted on.",
                    messages.WARNING,
                )
            return None
    return _action_page(
        request,
        modeladmin=modeladmin,
        form=form,
        items=queryset,
        copy=_ActionCopy(
            action="decide_notices",
            lead="Deciding on:",
            consequence=_REPORT_CONSEQUENCE,
            submit_label="Close notices",
        ),
    )


@admin.action(description="Decide on selected chat reports")
def decide_chat_reports(
    modeladmin: _ActionAdmin, request: HttpRequest, queryset: QuerySet[ParleyReport]
) -> HttpResponse | None:
    form = VerdictForm(request.POST if "apply" in request.POST else None)
    if form.is_valid():
        try:
            result = _services().moderation_decisions.decide_chat_reports(
                report_ids=list(queryset.values_list("pk", flat=True)),
                verdict=form.verdict(),
            )
        except InvalidVerdictError as error:
            form.add_error(None, str(error))
        else:
            modeladmin.message_user(
                request, f"Decided {result.decided} chat report(s)."
            )
            _report_statements(modeladmin, request, result)
            return None
    return _action_page(
        request,
        modeladmin=modeladmin,
        form=form,
        items=queryset,
        copy=_ActionCopy(
            action="decide_chat_reports",
            lead="Deciding on:",
            consequence=_REPORT_CONSEQUENCE,
            submit_label="Close chat reports",
        ),
    )


class RemovalForm(forms.Form):
    ground = forms.ChoiceField(
        choices=MODERATION_GROUND_CHOICES,
        help_text="The law, or the point of § 4.1 the message broke.",
    )
    legal_provision = forms.CharField(
        max_length=LEGAL_PROVISION_MAX_LENGTH,
        required=False,
        help_text=(
            "Required when the ground is the law: the provision broken, e.g."
            " art. 190 § 1 Kodeksu karnego."
        ),
    )
    decision_text = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 5}),
        max_length=DECISION_TEXT_MAX_LENGTH,
        help_text=_DECISION_TEXT_HELP,
    )

    def verdict(self) -> ModerationVerdict:
        data = self.cleaned_data
        return ModerationVerdict(
            status=ModerationStatus.ACTIONED,
            decision=ModerationDecision.CONTENT_REMOVED,
            ground=ModerationGround(data["ground"]),
            legal_provision=data["legal_provision"],
            decision_text=data["decision_text"],
        )


@admin.action(
    description="Delete the reported messages for everyone", permissions=["change"]
)
def delete_reported_messages(
    modeladmin: _ActionAdmin, request: HttpRequest, queryset: QuerySet[ParleyReport]
) -> HttpResponse | None:
    form = RemovalForm(request.POST if "apply" in request.POST else None)
    if form.is_valid():
        verdict = form.verdict()
        services = _services()
        try:
            services.moderation_decisions.check(verdict)
        except InvalidVerdictError as error:
            form.add_error(None, str(error))
        else:
            messages_reported = set(queryset.values_list("room_id", "message_id"))
            result = services.parley.delete_reported(
                report_ids=list(queryset.values_list("pk", flat=True)),
                now=datetime.now(UTC),
            )
            modeladmin.message_user(request, f"Deleted {result.deleted} message(s).")
            if result.failed:
                modeladmin.message_user(
                    request,
                    f"{result.failed} could not be deleted: the chat Worker did"
                    " not answer.",
                    messages.ERROR,
                )
            # NOTE: deleting resolves every report of each message it reached;
            # those are the reports this decision closes.
            removed = [
                pk
                for pk, room_id, message_id in ParleyReport.objects.filter(
                    status=ModerationStatus.OPEN, resolved_at__isnull=False
                ).values_list("pk", "room_id", "message_id")
                if (room_id, message_id) in messages_reported
            ]
            if removed:
                _report_statements(
                    modeladmin,
                    request,
                    services.moderation_decisions.decide_chat_reports(
                        report_ids=removed, verdict=verdict
                    ),
                )
            return None
    return _action_page(
        request,
        modeladmin=modeladmin,
        form=form,
        items=queryset,
        copy=_ActionCopy(
            action="delete_reported_messages",
            lead="Deleting for everyone the messages reported in:",
            consequence=(
                "Each deleted message closes its reports as actioned: every"
                " reporter hears the outcome and its author gets a statement of"
                " reasons."
            ),
            submit_label="Delete messages",
        ),
    )


def _never(
    _modeladmin: _ActionAdmin, _request: HttpRequest, _obj: Model | None = None
) -> bool:
    return False


admin.site.register(
    ContentNotice,
    list_display=(
        "case",
        "created_at",
        "category",
        "status",
        "url",
        "reporter_email",
        "resolved_at",
    ),
    list_filter=("status", "category"),
    list_select_related=("case",),
    search_fields=("url", "explanation", "reporter_email", "reporter_name"),
    # A notice stays as sent; the decide action is the only way to close it,
    # so a closed one has always mailed its outcome.
    has_change_permission=_never,
    actions=(decide_notices,),
    has_add_permission=_never,
)
admin.site.register(
    StatementOfReasons,
    list_display=("case", "created_at", "user", "decision", "ground", "from_report"),
    list_filter=("decision", "ground", "from_report", "automated"),
    list_select_related=("case", "user"),
    has_change_permission=_never,
    has_add_permission=_never,
)


# NOTE: options in place of a ModelAdmin subclass, which strict mypy
# would only take with a type: ignore.
admin.site.register(
    ParleyReport,
    actions=(decide_chat_reports, delete_reported_messages),
    list_display=(
        "created_at",
        "room_id",
        "sphere",
        "reporter",
        "reported_user",
        "body",
        "status",
        "resolved_at",
    ),
    # A report with no sphere came from a party's chat or a conversation.
    list_filter=(
        "status",
        ("resolved_at", admin.EmptyFieldListFilter),
        ("sphere", admin.EmptyFieldListFilter),
    ),
    list_select_related=("reporter", "reported_user", "sphere"),
    search_fields=("body", "author_name", "room_id"),
    # What the room said stays as reported. Only the actions close a report,
    # so a closed one has always mailed its outcome.
    readonly_fields=(
        "sphere",
        "conversation",
        "reporter",
        "room_id",
        "message_id",
        "reason",
        "reported_user",
        "author_name",
        "body",
        "written_at",
        "deleted_at",
        "created_at",
        "resolved_at",
        "case",
        "status",
        "decision",
        "ground",
        "legal_provision",
        "suspended_until",
        "decision_text",
    ),
)


@admin.register(AgendaItem)
class AgendaItemAdmin(admin.ModelAdmin):  # type: ignore [type-arg]
    ...


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):  # type: ignore [type-arg]
    prepopulated_fields: ClassVar[dict[str, Sequence[str]]] = {"slug": ("name",)}


@admin.register(EventProposalSettings)
class EventProposalSettingsAdmin(admin.ModelAdmin):  # type: ignore [type-arg]
    list_display = ("event", "allow_anonymous_proposals")
    list_filter = ("allow_anonymous_proposals",)


@admin.register(Space)
class SpaceAdmin(admin.ModelAdmin):  # type: ignore [type-arg]
    prepopulated_fields: ClassVar[dict[str, Sequence[str]]] = {"slug": ("name",)}


class SessionFieldValueInline(admin.TabularInline):  # type: ignore [type-arg]
    model = SessionFieldValue
    extra = 0
    fields = ("field", "value")


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):  # type: ignore [type-arg]
    list_display = ("title", "status", "facilitator_name", "category", "event")
    list_filter = ("status", "event")
    search_fields = ("title", "facilitator_name")
    prepopulated_fields: ClassVar[dict[str, Sequence[str]]] = {"slug": ("title",)}
    inlines = (SessionFieldValueInline,)


class SphereMembershipInline(admin.TabularInline):  # type: ignore [type-arg]
    model = SphereMembership
    extra = 0
    autocomplete_fields = ("user",)


@admin.register(Sphere)
class SphereAdmin(admin.ModelAdmin):  # type: ignore [type-arg]
    inlines = (SphereMembershipInline,)
    exclude = ("managers",)


class SendNotificationForm(forms.Form):
    kind = forms.ChoiceField(
        choices=[(item.value, item.name) for item in NotificationKind],
        initial=NotificationKind.WAITLIST_PROMOTED.value,
    )
    title = forms.CharField(max_length=255)
    body = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)
    url = forms.CharField(
        max_length=512,
        required=False,
        help_text=(
            "Leave empty for a content notification (opens in the overlay). "
            "A path like /events/ makes it a destination notification."
        ),
    )


@admin.register(User)
class UserAdmin(admin.ModelAdmin):  # type: ignore [type-arg]
    list_display = ("name", "user_type", "email", "discord_username")
    search_fields = ("name", "email")
    prepopulated_fields: ClassVar[dict[str, Sequence[str]]] = {"slug": ("name",)}

    @override
    def save_model(
        self, request: HttpRequest, obj: User, form: forms.ModelForm[User], change: bool
    ) -> None:
        super().save_model(request, obj, form, change)
        # NOTE: who may chat, and which parties' chats someone is in, hang
        # on these; the service pages that change them do the same.
        if change and {"is_active", "age_band"} & set(form.changed_data):
            _services().parley_revocations.revoke_user(user_id=obj.pk)

    @override
    def delete_model(self, request: HttpRequest, obj: User) -> None:
        chats = _services().parley_party_chats
        parties = chats.parties_of(obj.pk)
        super().delete_model(request, obj)
        for party_id in parties:
            chats.sync_party(party_id)

    @override
    def delete_queryset(self, request: HttpRequest, queryset: QuerySet[User]) -> None:
        chats = _services().parley_party_chats
        parties = {
            party_id
            for user_id in queryset.values_list("pk", flat=True)
            for party_id in chats.parties_of(user_id)
        }
        super().delete_queryset(request, queryset)
        for party_id in sorted(parties):
            chats.sync_party(party_id)

    @admin.action(description="Send notification to selected users")
    def send_notification(
        self, request: HttpRequest, queryset: QuerySet[User]
    ) -> HttpResponse | None:
        form = SendNotificationForm(request.POST if "apply" in request.POST else None)
        if form.is_valid():
            sent = ring_as_written(
                recipient_ids=queryset.values_list("pk", flat=True),
                bell=Bell(
                    kind=NotificationKind(form.cleaned_data["kind"]),
                    title=form.cleaned_data["title"],
                    body=form.cleaned_data["body"],
                    url=form.cleaned_data["url"],
                ),
            )
            self.message_user(request, f"Notification sent to {sent} user(s).")
            return None
        return render(
            request,
            "admin/send_notification.html",
            {
                **self.admin_site.each_context(request),
                "title": "Send notification",
                "form": form,
                "users": queryset,
                "action_checkbox_name": helpers.ACTION_CHECKBOX_NAME,
            },
        )

    @admin.action(description="Send a statement of reasons to selected users")
    def send_statement_of_reasons(
        self, request: HttpRequest, queryset: QuerySet[User]
    ) -> HttpResponse | None:
        form = StatementForm(request.POST if "apply" in request.POST else None)
        if form.is_valid():
            data = form.cleaned_data
            statements = _services().statements_of_reasons
            try:
                issued = [
                    statement
                    for user_id in queryset.values_list("pk", flat=True)
                    if (
                        statement := statements.issue(
                            StatementOfReasonsData(
                                user_id=user_id,
                                case_id=None,
                                decision=ModerationDecision(data["decision"]),
                                ground=ModerationGround(data["ground"]),
                                legal_provision=data["legal_provision"],
                                suspended_until=data["suspended_until"],
                                facts=data["facts"],
                                from_report=False,
                            )
                        )
                    )
                ]
            except InvalidVerdictError as error:
                form.add_error(None, str(error))
            else:
                _report_statements(
                    self, request, ModerationDecisionsDTO(decided=0, statements=issued)
                )
                return None
        return _action_page(
            request,
            modeladmin=self,
            form=form,
            items=queryset,
            copy=_ActionCopy(
                action="send_statement_of_reasons",
                lead="Sending to:",
                consequence=(
                    "Send it when you act on content or an account outside a"
                    " report. Before removing an account, send it first, while"
                    " the address is still on record."
                ),
                submit_label="Send statement of reasons",
            ),
        )

    # Referenced by object, not by name: vulture cannot see a string-named action
    # being used and reports the method as dead code.
    actions = (send_notification, send_statement_of_reasons)


@admin.register(Facilitator)
class FacilitatorAdmin(admin.ModelAdmin):  # type: ignore [type-arg]
    list_display = ("display_name", "event", "user", "accreditation_type")
    list_filter = ("event", "accreditation_type")
    prepopulated_fields: ClassVar[dict[str, Sequence[str]]] = {
        "slug": ("display_name",)
    }


@admin.register(ProposalCategory)
class ProposalCategoryAdmin(admin.ModelAdmin):  # type: ignore [type-arg]
    prepopulated_fields: ClassVar[dict[str, Sequence[str]]] = {"slug": ("name",)}


@admin.register(EnrollmentConfig)
class EnrollmentConfigAdmin(admin.ModelAdmin):  # type: ignore [type-arg]
    list_display = (
        "event",
        "start_time",
        "end_time",
        "percentage_slots",
        "restrict_to_configured_users",
        "allow_anonymous_enrollment",
    )
    list_filter = (
        "restrict_to_configured_users",
        "allow_anonymous_enrollment",
        "event",
    )
    fields = (
        "event",
        "start_time",
        "end_time",
        "percentage_slots",
        "limit_to_end_time",
        "restrict_to_configured_users",
        "allow_anonymous_enrollment",
        "max_waitlist_sessions",
        "banner_text",
    )


@admin.register(UserEnrollmentConfig)
class UserEnrollmentConfigAdmin(admin.ModelAdmin):  # type: ignore [type-arg]
    list_display = (
        "user_email",
        "enrollment_config",
        "allowed_slots",
        "fetched_from_api",
    )
    list_filter = ("fetched_from_api", "enrollment_config__event")
    search_fields = ("user_email",)


@admin.register(DomainEnrollmentConfig)
class DomainEnrollmentConfigAdmin(admin.ModelAdmin):  # type: ignore [type-arg]
    list_display = ("domain", "enrollment_config", "allowed_slots_per_user")
    list_filter = ("enrollment_config__event",)
    search_fields = ("domain",)
    fields = ("enrollment_config", "domain", "allowed_slots_per_user")


@admin.register(Encounter)
class EncounterAdmin(admin.ModelAdmin):  # type: ignore [type-arg]
    list_display = (
        "title",
        "sphere",
        "creator",
        "start_time",
        "share_code",
        "is_public",
    )
    list_filter = ("sphere", "is_public")
    search_fields = ("title",)


@admin.register(EncounterRSVP)
class EncounterRSVPAdmin(admin.ModelAdmin):  # type: ignore [type-arg]
    list_display = ("encounter", "user", "creation_time")
    list_filter = ("encounter",)


@admin.register(TagCategory)
class TagCategoryAdmin(admin.ModelAdmin):  # type: ignore [type-arg]
    list_display = ("name", "slug")
    prepopulated_fields: ClassVar[dict[str, Sequence[str]]] = {"slug": ("name",)}


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):  # type: ignore [type-arg]
    list_display = ("__str__", "category", "slug")
    list_filter = ("category",)
    list_select_related = ("category", "parent__parent")
    search_fields = ("name", "search_key")
    autocomplete_fields = ("parent",)
    prepopulated_fields: ClassVar[dict[str, Sequence[str]]] = {"slug": ("name",)}
