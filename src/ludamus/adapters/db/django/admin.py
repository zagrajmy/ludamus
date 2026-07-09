from typing import TYPE_CHECKING, ClassVar, cast

from django import forms
from django.contrib import admin

from ludamus.adapters.db.django.models import (
    AgendaItem,
    DomainEnrollmentConfig,
    Encounter,
    EncounterRSVP,
    EnrollmentConfig,
    Event,
    EventProposalSettings,
    Facilitator,
    ProposalCategory,
    Session,
    SessionFieldValue,
    Space,
    Sphere,
    Tag,
    TagCategory,
    TimeSlot,
    User,
    UserEnrollmentConfig,
)
from ludamus.pacts import SpherePage

if TYPE_CHECKING:
    from collections.abc import Sequence


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
    list_display = ("title", "status", "display_name", "category", "event")
    list_filter = ("status", "event")
    search_fields = ("title", "display_name")
    prepopulated_fields: ClassVar[dict[str, Sequence[str]]] = {"slug": ("title",)}
    inlines = (SessionFieldValueInline,)


class SphereAdminForm(forms.ModelForm):  # type: ignore [type-arg]
    enabled_pages = forms.MultipleChoiceField(
        choices=[(p.value, p.value.title()) for p in SpherePage],
        widget=forms.SelectMultiple,
    )

    def clean(self) -> dict[str, object]:
        cleaned: dict[str, object] = super().clean() or {}
        default_page = cleaned.get("default_page")
        enabled_pages = cast("list[str]", cleaned.get("enabled_pages") or [])
        if default_page and default_page not in enabled_pages:
            self.add_error(
                "default_page", "Default page must be one of the enabled pages."
            )
        return cleaned


@admin.register(Sphere)
class SphereAdmin(admin.ModelAdmin):  # type: ignore [type-arg]
    form = SphereAdminForm


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):  # type: ignore [type-arg]
    ...


@admin.register(TagCategory)
class TagCategoryAdmin(admin.ModelAdmin):  # type: ignore [type-arg]
    ...


@admin.register(TimeSlot)
class TimeSlotAdmin(admin.ModelAdmin):  # type: ignore [type-arg]
    ...


@admin.register(User)
class UserAdmin(admin.ModelAdmin):  # type: ignore [type-arg]
    list_display = ("name", "user_type", "email", "discord_username")
    prepopulated_fields: ClassVar[dict[str, Sequence[str]]] = {"slug": ("name",)}


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
    list_display = ("title", "sphere", "creator", "start_time", "share_code")
    list_filter = ("sphere",)
    search_fields = ("title",)


@admin.register(EncounterRSVP)
class EncounterRSVPAdmin(admin.ModelAdmin):  # type: ignore [type-arg]
    list_display = ("encounter", "user", "ip_address", "creation_time")
    list_filter = ("encounter",)
