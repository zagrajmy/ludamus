from __future__ import annotations

import logging
from datetime import UTC, datetime
from secrets import token_urlsafe
from typing import TYPE_CHECKING, ClassVar

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.shortcuts import render

from ludamus.links.db.django.delivery import Bell, ring_as_written
from ludamus.links.db.django.models import (
    AgendaItem,
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
    Tag,
    TagCategory,
    TimeSlot,
    User,
    UserEnrollmentConfig,
)
from ludamus.links.encryption import JwtSigner
from ludamus.links.parley_worker import ParleyWorkerClient
from ludamus.pacts.notifications import NotificationKind
from ludamus.pacts.parley import ParleyMessageLookupClaims, ParleyWorkerUnavailableError

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.db.models import QuerySet
    from django.http import HttpRequest, HttpResponse


# A lookup's claims on another audience: the Worker takes this one as the
# order to delete the message, as staff, for everyone in the room.
_MODERATION_AUDIENCE = "parley-moderation"
_MODERATION_LIFETIME_SECONDS = 60


@admin.action(description="Delete the reported messages for everyone")
def delete_reported_messages(
    modeladmin: admin.ModelAdmin[ParleyReport],
    request: HttpRequest,
    queryset: QuerySet[ParleyReport],
) -> None:
    agent_host: str = settings.PARLEY_AGENT_HOST
    private_key: str = settings.PARLEY_SIGNING_PRIVATE_KEY
    if not (agent_host and private_key):
        modeladmin.message_user(
            request, "The chat Worker is not configured.", level=messages.ERROR
        )
        return
    signer, worker = JwtSigner(private_key), ParleyWorkerClient(agent_host)
    deleted = failed = 0
    for report in queryset:
        now = datetime.now(UTC)
        issued = int(now.timestamp())
        try:
            worker.moderate(
                signer.sign(
                    ParleyMessageLookupClaims(
                        iss="ludamus",
                        aud=_MODERATION_AUDIENCE,
                        room=report.room_id,
                        message=report.message_id,
                        iat=issued,
                        exp=issued + _MODERATION_LIFETIME_SECONDS,
                        jti=token_urlsafe(18),
                    )
                )
            )
        except ParleyWorkerUnavailableError:
            logger.exception(
                "parley staff deletion failed: report=%s room=%s",
                report.pk,
                report.room_id,
            )
            failed += 1
            continue
        logger.info(
            "parley message deleted by staff: report=%s room=%s message=%s",
            report.pk,
            report.room_id,
            report.message_id,
        )
        ParleyReport.objects.filter(
            room_id=report.room_id, message_id=report.message_id, resolved_at=None
        ).update(resolved_at=now)
        deleted += 1
    modeladmin.message_user(request, f"Deleted {deleted} message(s).")
    if failed:
        modeladmin.message_user(
            request,
            f"{failed} could not be deleted: the chat Worker did not answer.",
            level=messages.ERROR,
        )


# NOTE: options in place of a ModelAdmin subclass, which strict mypy
# would only take with a type: ignore.
admin.site.register(
    ParleyReport,
    actions=(delete_reported_messages,),
    list_display=(
        "created_at",
        "room_id",
        "sphere",
        "reporter",
        "reported_user",
        "body",
        "resolved_at",
    ),
    # A report with no sphere came from a party's chat or a conversation.
    list_filter=(
        ("resolved_at", admin.EmptyFieldListFilter),
        ("sphere", admin.EmptyFieldListFilter),
    ),
    list_select_related=("reporter", "reported_user", "sphere"),
    search_fields=("body", "author_name", "room_id"),
    # What the room said stays as reported; staff only mark it resolved.
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

    # Referenced by object, not by name: vulture cannot see a string-named action
    # being used and reports the method as dead code.
    actions = (send_notification,)


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
