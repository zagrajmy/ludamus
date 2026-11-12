from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Protocol

from django import forms
from django.contrib import admin
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
    TimeSlot,
    User,
    UserEnrollmentConfig,
)
from ludamus.pacts.moderation import (
    DECISION_TEXT_MAX_LENGTH,
    InvalidVerdictError,
    ModerationDecision,
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


def register_services(make_services: Callable[[], ServicesProtocol]) -> None:
    """Hand the admin its services. Called once, at startup, by `inits`.

    The admin runs outside the app middleware, so its requests carry no
    services of their own.
    """
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


class StatementForm(forms.Form):
    decision = forms.ChoiceField(choices=_ACTION_DECISIONS)
    ground = forms.ChoiceField(choices=MODERATION_GROUND_CHOICES)
    facts = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 5}),
        max_length=DECISION_TEXT_MAX_LENGTH,
        help_text="What was done and why, as the person will read it.",
    )


class VerdictForm(forms.Form):
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
        user = User.objects.filter(
            Q(username=identifier) | Q(email__iexact=identifier) | Q(slug=identifier)
        ).first()
        if user is None:
            msg = "No account by that username or email."
            raise forms.ValidationError(msg)
        return user.pk


class _ActionAdmin(Protocol):
    admin_site: AdminSite

    def message_user(self, request: HttpRequest, message: str) -> None: ...


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
        try:
            decided = _services().moderation_decisions.decide_notices(
                notice_ids=list(queryset.values_list("pk", flat=True)),
                verdict=form.verdict(),
                affected_user_id=form.cleaned_data["affected_account"],
            )
        except InvalidVerdictError as error:
            form.add_error(None, str(error))
        else:
            modeladmin.message_user(request, f"Decided {decided} notice(s).")
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
            decided = _services().moderation_decisions.decide_chat_reports(
                report_ids=list(queryset.values_list("pk", flat=True)),
                verdict=form.verdict(),
            )
        except InvalidVerdictError as error:
            form.add_error(None, str(error))
        else:
            modeladmin.message_user(request, f"Decided {decided} chat report(s).")
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
    list_display=(
        "created_at",
        "room_id",
        "reporter",
        "reported_user",
        "body",
        "status",
        "resolved_at",
    ),
    list_filter=(("resolved_at", admin.EmptyFieldListFilter), "status"),
    list_select_related=("reporter", "reported_user"),
    search_fields=("body", "author_name", "room_id"),
    # What the room said stays as reported. The decide action is the only way
    # to close a report, so a closed one has always mailed its outcome.
    has_change_permission=_never,
    actions=(decide_chat_reports,),
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


@admin.register(TimeSlot)
class TimeSlotAdmin(admin.ModelAdmin):  # type: ignore [type-arg]
    ...


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
            statements = _services().statements_of_reasons
            for user_id in queryset.values_list("pk", flat=True):
                statements.issue(
                    StatementOfReasonsData(
                        user_id=user_id,
                        case_id=None,
                        decision=ModerationDecision(form.cleaned_data["decision"]),
                        ground=ModerationGround(form.cleaned_data["ground"]),
                        facts=form.cleaned_data["facts"],
                        from_report=False,
                    )
                )
            self.message_user(
                request, f"Statement of reasons sent to {queryset.count()} user(s)."
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
