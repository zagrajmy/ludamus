from __future__ import annotations

import math
import sys
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, ClassVar, Never, TypeVar, cast

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, UserManager
from django.contrib.sites.models import Site
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.timezone import localtime
from django.utils.translation import gettext_lazy as _

from ludamus.pacts import (
    OCCUPYING_PARTICIPATION_STATUSES,
    NotificationKind,
    PromotionMode,
    SessionParticipationStatus,
    SessionStatus,
    SpherePage,
)
from ludamus.pacts.crowd import UserType
from ludamus.pacts.discounts import DiscountKind
from ludamus.pacts.party import PartyConsentMode, PartyMembershipStatus
from ludamus.pacts.submissions import ImportLogStatus

if TYPE_CHECKING:
    from collections.abc import Collection, Iterator

    from ludamus.pacts.crowd import UserDTO


MAX_SLUG_RETRIES = 10
RANDOM_SLUG_BYTES = 7  # 10 characters
SPACE_MAX_DEPTH = 7  # root = depth 1; the tree may nest at most this deep
DEFAULT_NAME = "Andrzej"
MAX_CONNECTED_USERS = 6  # Maximum number of connected users per manager


_SoftDeleteT = TypeVar("_SoftDeleteT", bound=models.Model)


class AliveManager(models.Manager[_SoftDeleteT]):
    # The default `objects` manager hides soft-deleted rows so every existing
    # read (including reverse relations like `category.sessions`) excludes them
    # automatically. Reach soft-deleted rows through `all_objects`.
    def get_queryset(self) -> models.QuerySet[_SoftDeleteT]:
        return super().get_queryset().filter(deleted_at__isnull=True)


class SoftDeleteModel(models.Model):
    # Null `deleted_at` = alive; a timestamp = deleted (reversible). The default
    # `objects` manager hides deleted rows; `all_objects` includes everything.
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects: ClassVar = AliveManager()
    all_objects: ClassVar = models.Manager()

    class Meta:
        abstract = True

    def soft_delete(self) -> None:
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at"])

    def restore(self) -> None:
        self.deleted_at = None
        self.save(update_fields=["deleted_at"])


class User(AbstractBaseUser, PermissionsMixin):
    EMAIL_FIELD = "email"
    USERNAME_FIELD = "username"
    REQUIRED_FIELDS: ClassVar = ["email"]

    date_joined = models.DateTimeField(_("date joined"), default=timezone.now)
    email = models.EmailField(_("email address"), blank=True)
    is_active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_(
            "Designates whether this user should be treated as active. "
            "Unselect this instead of deleting accounts."
        ),
    )
    is_staff = models.BooleanField(
        _("staff status"),
        default=False,
        help_text=_("Designates whether the user can log into this admin site."),
    )
    name = models.CharField(_("User name"), max_length=255, blank=True)
    slug = models.SlugField(unique=True, db_index=True)
    user_type = models.CharField(
        max_length=255,
        choices=[(t.value, t.name) for t in UserType],
        default=UserType.ACTIVE,
    )
    username = models.CharField(
        _("username"),
        max_length=150,
        unique=True,
        help_text=_(
            "Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only."
        ),
        error_messages={"unique": _("A user with that username already exists.")},
    )
    discord_username = models.CharField(
        _("Discord username"),
        max_length=150,
        blank=True,
        help_text=_("Your Discord username for session coordination"),
    )
    avatar_url = models.URLField(
        _("Avatar URL"),
        blank=True,
        default="",
        help_text=_("Profile avatar URL (e.g. from Auth0)"),
    )
    use_gravatar = models.BooleanField(
        _("Use Gravatar"),
        default=False,
        help_text=_("Use Gravatar instead of provider avatar"),
    )
    # Single-use handle that lets the intended person sign in and take over a
    # managed (connected) row as their own account. Mirrors the waitlist-offer
    # claim_token pattern. Empty for active accounts.
    claim_token = models.CharField(max_length=64, blank=True, default="", db_index=True)
    shadowbanned: models.ManyToManyField[User, Shadowban] = models.ManyToManyField(
        "self",
        symmetrical=False,
        through="Shadowban",
        through_fields=("owner", "target"),
        related_name="shadowbanned_by",
        blank=True,
    )

    objects = UserManager()

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>"

    def get_full_name(self) -> str:
        return self.name or DEFAULT_NAME

    @property
    def full_name(self) -> str:
        return self.get_full_name()

    class Meta:
        db_table = "user"
        verbose_name = _("user")
        verbose_name_plural = _("users")

        constraints = (
            models.UniqueConstraint(
                Lower("email").desc(),
                name="constraint_unique_email_lower_no_null",
                condition=~Q(email=""),
            ),
        )


class Shadowban(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    target = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "shadowban"
        constraints = (
            models.CheckConstraint(
                condition=~Q(owner=F("target")), name="shadowban_owner_not_target"
            ),
            models.UniqueConstraint(
                fields=("owner", "target"), name="shadowban_unique_owner_target"
            ),
        )

    def __str__(self) -> str:
        return f"{self.owner_id} shadowbanned {self.target_id}"


REASON_MAX_LENGTH = 255  # EventBan.reason column width; reused by the safety repo


class EventBan(models.Model):
    event = models.ForeignKey("Event", on_delete=models.CASCADE, related_name="bans")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="event_bans")
    reason = models.CharField(max_length=REASON_MAX_LENGTH, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "event_ban"
        constraints = (
            models.UniqueConstraint(
                fields=("event", "user"), name="event_ban_unique_event_user"
            ),
        )

    def __str__(self) -> str:
        return f"{self.user_id} banned from event {self.event_id}"


class Party(models.Model):
    # The group that enrolls together. See RFC 0001.
    name = models.CharField(max_length=255, blank=True, default="")
    leader = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="led_parties"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "party"

    def __str__(self) -> str:
        return f"{self.name or 'party'} (#{self.pk})"


class PartyMembership(models.Model):
    party = models.ForeignKey(
        Party, on_delete=models.CASCADE, related_name="memberships"
    )
    member = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="party_memberships"
    )
    consent_mode = models.CharField(
        max_length=32,
        choices=[(c.value, c.name) for c in PartyConsentMode],
        default=PartyConsentMode.ACCEPT_INVITES,
    )
    status = models.CharField(
        max_length=32,
        choices=[(s.value, s.name) for s in PartyMembershipStatus],
        default=PartyMembershipStatus.ACTIVE,
    )

    class Meta:
        db_table = "party_membership"
        constraints = (
            models.UniqueConstraint(
                fields=("party", "member"), name="party_membership_unique"
            ),
        )

    def __str__(self) -> str:
        return f"{self.member_id} in party {self.party_id}"


class SessionBookmark(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="session_bookmarks"
    )
    session = models.ForeignKey(
        "Session", on_delete=models.CASCADE, related_name="bookmarks"
    )
    creation_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "session_bookmark"
        constraints = (
            models.UniqueConstraint(
                fields=("user", "session"), name="session_bookmark_unique_user_session"
            ),
        )

    def __str__(self) -> str:
        return f"{self.user_id} bookmarked session {self.session_id}"


class Sphere(models.Model):
    """Big group for whole provinces, topics, organizations or big events."""

    name = models.CharField(max_length=255)
    site = models.OneToOneField(Site, on_delete=models.PROTECT, related_name="sphere")
    managers = models.ManyToManyField(User)
    # Branding fallback — used on printables when an event has no logo of its own
    logo = models.ImageField(upload_to="spheres/", blank=True)
    enabled_pages = models.JSONField(
        default=SpherePage.all_values,
        help_text="List of enabled page identifiers, e.g. ['events', 'encounters']",
    )
    default_page = models.CharField(
        max_length=20,
        choices=[(p.value, p.name.title()) for p in SpherePage],
        default=SpherePage.EVENTS,
    )
    allow_facilitator_session_edit = models.BooleanField(default=True)

    class Meta:
        db_table = "sphere"

    def __str__(self) -> str:
        return self.name

    @property
    def logo_url(self) -> str:
        return self.logo.url if self.logo else ""


class Event(models.Model):
    # Owner
    sphere = models.ForeignKey(Sphere, on_delete=models.CASCADE, related_name="events")
    # ID
    name = models.CharField(max_length=255)
    slug = models.SlugField()
    description = models.TextField(default="", blank=True)
    cover_image = models.ImageField(upload_to="events/", blank=True)
    # Branding — shown on printables (the public /print page)
    logo = models.ImageField(upload_to="events/", blank=True)
    # Time - start and end
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    # Publication time
    publication_time = models.DateTimeField(blank=True, null=True)
    # Proposal times
    proposal_start_time = models.DateTimeField(blank=True, null=True)
    proposal_end_time = models.DateTimeField(blank=True, null=True)
    # Printables reminder: when an organizer first opened a print-ready page, and
    # when the "print your materials" reminder email went out. Both drive the
    # pre-event reminder sweep — organizers who already printed are skipped.
    printables_last_printed_at = models.DateTimeField(blank=True, null=True)
    printables_reminder_sent_at = models.DateTimeField(blank=True, null=True)
    allow_facilitator_session_edit = models.BooleanField(
        null=True, blank=True, default=None
    )
    use_session_cover_placeholders = models.BooleanField(default=False)
    # Label for the enrolled-people count on the public event page: off →
    # "Players" (gaming events), on → "Participants" (general events).
    use_participants_label = models.BooleanField(default=False)
    # When on, newly scheduled program items are confirmed immediately;
    # turn off for a draft → confirm workflow on large events.
    auto_confirm_sessions = models.BooleanField(default=True)

    class Meta:
        db_table = "event"
        constraints = (
            models.UniqueConstraint(
                fields=("sphere", "slug"), name="event_has_unique_slug_and_sphere"
            ),
            models.CheckConstraint(
                condition=Q(
                    publication_time__isnull=True,
                    start_time__isnull=True,
                    end_time__isnull=True,
                )
                | Q(
                    publication_time__lte=F("start_time"), start_time__lt=F("end_time")
                ),
                name="event_date_times",
            ),
        )

    def __str__(self) -> str:
        return self.name

    @property
    def cover_image_url(self) -> str:
        return self.cover_image.url if self.cover_image else ""

    @property
    def logo_url(self) -> str:
        return self.logo.url if self.logo else ""

    @property
    def is_proposal_active(self) -> bool:
        return (
            self.proposal_start_time is not None
            and self.proposal_end_time is not None
            and (
                self.proposal_start_time < datetime.now(tz=UTC) < self.proposal_end_time
            )
        )

    @property
    def is_live(self) -> bool:
        return self.start_time < datetime.now(tz=UTC) < self.end_time

    @property
    def is_ended(self) -> bool:
        return self.end_time < datetime.now(tz=UTC)

    @property
    def is_published(self) -> bool:
        return (
            self.publication_time is not None
            and self.publication_time <= datetime.now(tz=UTC)
        )

    def get_active_enrollment_configs(self) -> list[EnrollmentConfig]:
        return [config for config in self.enrollment_configs.all() if config.is_active]

    def get_most_liberal_config(self, session: Session) -> EnrollmentConfig | None:
        eligible_configs = [
            config
            for config in self.get_active_enrollment_configs()
            if config.is_session_eligible(session)
        ]

        if not eligible_configs:
            return None

        return max(eligible_configs, key=lambda c: c.percentage_slots)


class EventProposalSettings(models.Model):
    event = models.OneToOneField(
        Event, on_delete=models.CASCADE, related_name="proposal_settings"
    )
    description = models.TextField(default="", blank=True)
    allow_anonymous_proposals = models.BooleanField(default=False)

    class Meta:
        db_table = "event_proposal_settings"

    def __str__(self) -> str:
        return f"Proposal settings for {self.event}"


class EnrollmentConfig(models.Model):
    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="enrollment_configs"
    )
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    percentage_slots = models.PositiveIntegerField(
        default=100,
        help_text="Percentage of total session slots available for enrollment (1-100)",
    )
    limit_to_end_time = models.BooleanField(
        default=False,
        help_text=(
            "Only allow enrollment for sessions starting before this config's end time"
        ),
    )
    banner_text = models.TextField(
        blank=True, help_text="Banner text to display for active enrollments"
    )
    max_waitlist_sessions = models.PositiveIntegerField(
        default=10,
        help_text=(
            "Maximum number of sessions a user can join waitlist for "
            "(0 = waitlist disabled)"
        ),
    )
    restrict_to_configured_users = models.BooleanField(
        default=False,
        help_text=(
            "Only allow users with explicit UserEnrollmentConfig entries to enroll"
        ),
    )
    allow_anonymous_enrollment = models.BooleanField(
        default=False,
        help_text="Allow anonymous users to enroll without creating accounts",
    )

    class Meta:
        db_table = "enrollment_config"
        constraints = (
            models.CheckConstraint(
                condition=Q(start_time__lt=F("end_time")),
                name="enrollment_config_date_times",
            ),
            models.CheckConstraint(
                condition=Q(percentage_slots__gte=1, percentage_slots__lte=100),
                name="enrollment_config_percentage_range",
            ),
        )

    def __str__(self) -> str:
        return f"Enrollment config for {self.event.name}"

    @property
    def is_active(self) -> bool:
        return self.start_time < datetime.now(tz=UTC) < self.end_time

    def get_available_slots(self, session: Session) -> int:
        """Calculate available enrollment slots for a session based on percentage.

        Returns:
            Number of available slots for enrollment.
        """
        if session.participants_limit == 0:
            return sys.maxsize
        effective_limit = math.ceil(
            session.participants_limit * self.percentage_slots / 100
        )
        current_enrolled = session.enrolled_count
        return max(0, effective_limit - current_enrolled)

    def is_session_eligible(self, session: Session) -> bool:
        """Check if session is eligible for enrollment under this config.

        Returns:
            True if session can be enrolled in under this config.
        """
        if self.limit_to_end_time:
            return session.agenda_item.start_time < self.end_time

        return True


class UserEnrollmentConfig(models.Model):
    enrollment_config = models.ForeignKey(
        EnrollmentConfig, on_delete=models.CASCADE, related_name="user_configs"
    )
    user_email = models.EmailField(
        help_text="Email address of the user this configuration applies to"
    )
    allowed_slots = models.PositiveIntegerField(
        help_text=(
            "Maximum number of users (including connected users) that can "
            "be enrolled by this account"
        )
    )
    fetched_from_api = models.BooleanField(
        default=False, help_text="Whether this config was fetched from external API"
    )
    last_check = models.DateTimeField(
        null=True, blank=True, help_text="Last time the membership was checked via API"
    )

    class Meta:
        db_table = "user_enrollment_config"
        constraints = (
            models.UniqueConstraint(
                fields=["enrollment_config", "user_email"],
                name="unique_user_enrollment_config",
            ),
        )

    def __str__(self) -> str:
        return f"{self.user_email}: {self.allowed_slots} people enrollment limit"


class DomainEnrollmentConfig(models.Model):
    enrollment_config = models.ForeignKey(
        EnrollmentConfig, on_delete=models.CASCADE, related_name="domain_configs"
    )
    domain = models.CharField(
        max_length=255, help_text="Domain name (e.g. 'company.com', 'university.edu')"
    )
    allowed_slots_per_user = models.PositiveIntegerField(
        help_text=(
            "Default number of users (including connected users) that can be enrolled "
            "by accounts from this domain"
        )
    )

    class Meta:
        db_table = "domain_enrollment_config"
        constraints = (
            models.UniqueConstraint(
                fields=["enrollment_config", "domain"],
                name="unique_domain_enrollment_config",
            ),
        )

    def __str__(self) -> str:
        return (
            f"@{self.domain}: {self.allowed_slots_per_user} people enrollment "
            "limit per account"
        )

    def clean(self) -> None:
        super().clean()
        # Normalize domain to lowercase
        if self.domain:
            self.domain = self.domain.lower().strip()
            # Remove @ prefix if present
            self.domain = self.domain.removeprefix("@")
            # Basic domain validation
            if "." not in self.domain:
                raise ValidationError(
                    "Please enter a valid domain (e.g. 'company.com')"
                )


class Space(models.Model):
    """A node in the event's space tree (building → … → bookable room)."""

    # Owner - denormalized event so leaf->event is direct (no deep-chain walk)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="spaces")
    # Tree - null parent = root node; nodes form the building->...->room hierarchy
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="children"
    )
    # ID
    name = models.CharField(max_length=255)
    slug = models.SlugField()
    # Details
    capacity = models.PositiveIntegerField(null=True, blank=True)
    description = models.TextField(blank=True, default="")
    # Ordering
    order = models.PositiveIntegerField(default=0)
    # Time
    creation_time = models.DateTimeField(auto_now_add=True)
    modification_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "space"
        ordering: ClassVar = ["order", "name"]
        constraints = (
            models.UniqueConstraint(
                fields=("slug", "parent"), name="space_has_unique_slug_and_parent"
            ),
            # SQL treats NULL parents as distinct, so the constraint above can't
            # police roots; a partial unique index enforces root slug uniqueness
            # per event at the DB level (mirrors _validate_root_slug_unique).
            models.UniqueConstraint(
                fields=("event", "slug"),
                condition=models.Q(parent__isnull=True),
                name="space_root_has_unique_slug_per_event",
            ),
        )

    def __str__(self) -> str:
        # "Root > ... > Leaf" path, recursing up via str(parent). ponytail: lazy
        # parent loads (one query per level) — fine for admin/debug __str__.
        return f"{self.parent} > {self.name}" if self.parent else self.name

    def iter_ancestors(self) -> Iterator[Space]:
        if self.parent is not None:
            yield self.parent
            yield from self.parent.iter_ancestors()

    def clean(self) -> None:
        super().clean()
        self._validate_same_event()
        self._validate_acyclic_and_depth()
        self._validate_leaf_parent()
        self._validate_root_slug_unique()

    def _validate_same_event(self) -> None:
        if self.parent is not None and self.parent.event_id != self.event_id:
            raise ValidationError(_("A space must belong to its parent's event."))

    def _validate_acyclic_and_depth(self) -> None:
        # Climb the parent chain. Revisiting self is a cycle; exceeding the max
        # depth (a runaway climb also implies a cycle) is rejected. Lazy
        # iteration stops at the first violation, so a cycle never loops forever.
        seen = {self.pk}
        for depth, ancestor in enumerate(self.iter_ancestors(), start=2):
            if ancestor.pk in seen:
                raise ValidationError(_("A space cannot be its own ancestor."))
            seen.add(ancestor.pk)
            if depth > SPACE_MAX_DEPTH:
                raise ValidationError(
                    _("Spaces can be nested at most %(max)d levels deep.")
                    % {"max": SPACE_MAX_DEPTH}
                )

    def _validate_leaf_parent(self) -> None:
        # Attaching under a parent turns that parent into a branch; a branch
        # cannot also hold a scheduled session.
        if self.parent is not None and self.parent.agenda_items.exists():
            raise ValidationError(
                _("A space holding a scheduled session cannot contain other spaces.")
            )

    def _validate_root_slug_unique(self) -> None:
        # The (slug, parent) DB constraint can't police roots (SQL treats NULL
        # parents as distinct), so root slug uniqueness lives here.
        if self.parent_id is not None:
            return
        clash = (
            Space.objects.filter(
                event_id=self.event_id, parent__isnull=True, slug=self.slug
            )
            .exclude(pk=self.pk)
            .exists()
        )
        if clash:
            raise ValidationError(
                {"slug": _("A root space with this slug already exists.")}
            )


class TimeSlot(models.Model):
    # Owner
    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="time_slots"
    )
    # Time
    end_time = models.DateTimeField()
    start_time = models.DateTimeField()

    class Meta:
        db_table = "time_slot"
        constraints = (
            models.UniqueConstraint(
                fields=("event", "start_time", "end_time"),
                name="timeslot_has_unique_times_for_event",
            ),
            models.CheckConstraint(
                condition=Q(start_time__lt=F("end_time")), name="timeslot_date_times"
            ),
        )

    def __str__(self) -> str:
        ts_format = "%Y-%m-%d %H:%M"
        start = localtime(self.start_time).strftime(ts_format)
        if self.start_time.date() == self.end_time.date():
            ts_format = "%H:%M"
        end = localtime(self.end_time).strftime(ts_format)
        return f"{start} - {end} ({self.id})"

    def validate_unique(self, exclude: Collection[str] | None = None) -> None:
        super().validate_unique(exclude)
        event_slots = TimeSlot.objects.filter(event=self.event)
        conflicted = event_slots.filter(
            Q(start_time__gt=self.start_time, start_time__lt=self.end_time)
            | Q(end_time__gt=self.start_time, end_time__lt=self.end_time)
            | Q(start_time__lte=self.start_time, end_time__gte=self.end_time)
        ).last()
        if conflicted and conflicted != self:
            raise ValidationError(_("Time slots can't overlap!"))


class AccreditationType(models.TextChoices):
    NONE = "none", _("None")
    STANDARD = "standard", _("Standard")
    GUEST = "guest", _("Guest")
    HONORARY = "honorary", _("Honorary")


class Facilitator(models.Model):
    """Program creator / session facilitator, decoupled from User accounts."""

    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="facilitators"
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="facilitator_profiles",
    )
    display_name = models.CharField(max_length=255)
    slug = models.SlugField()
    accreditation_type = models.CharField(
        max_length=20, choices=AccreditationType.choices, default=AccreditationType.NONE
    )
    # Reversible triage marker: organizers flag likely duplicates/removals, then
    # act on them (merge or delete) as a separate deliberate step.
    flagged_for_deletion = models.BooleanField(default=False)
    # Free-form organizer note, never shown to attendees.
    internal_comment = models.TextField(blank=True, default="")

    class Meta:
        db_table = "facilitator"
        verbose_name = _("Twórca programu")
        verbose_name_plural = _("Twórcy programu")
        constraints = (
            models.UniqueConstraint(
                fields=("event", "slug"), name="facilitator_unique_slug_per_event"
            ),
        )

    def __str__(self) -> str:
        return self.display_name


class SessionManager(AliveManager["Session"]):
    # Inherits the alive-only `get_queryset` from AliveManager so conflict
    # checks (and the default `objects` accessor) skip soft-deleted sessions.
    def conflicted_user_ids(self, session: Session, user_ids: list[int]) -> set[int]:
        if not user_ids:
            return set()
        start = session.agenda_item.start_time
        end = session.agenda_item.end_time
        return set(
            self.get_queryset()
            .filter(
                event_id=session.event_id,
                session_participations__user_id__in=user_ids,
                session_participations__status=SessionParticipationStatus.CONFIRMED,
            )
            .filter(
                Q(agenda_item__start_time__gte=start, agenda_item__start_time__lt=end)
                | Q(agenda_item__end_time__gt=start, agenda_item__end_time__lte=end)
            )
            .exclude(id=session.id)
            .values_list("session_participations__user_id", flat=True)
        )

    def has_conflicts(self, session: Session, user: UserDTO) -> bool:
        return user.pk in self.conflicted_user_ids(session, [user.pk])


class Session(SoftDeleteModel):
    """Session model."""

    # Owner
    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="event_sessions"
    )
    presenter = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="presented_sessions",
    )

    facilitators = models.ManyToManyField(
        Facilitator, blank=True, related_name="sessions"
    )
    display_name = models.CharField(max_length=255)
    contact_email = models.EmailField(default="", blank=True)
    category = models.ForeignKey(
        "ProposalCategory",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="sessions",
    )
    # ID
    title = models.CharField(max_length=255)
    slug = models.SlugField()
    # Import idempotency key (hash of the source row's unique-key values).
    # Empty for sessions that weren't imported; never shown to users.
    ident = models.CharField(max_length=64, default="", blank=True)
    description = models.TextField(default="", blank=True)
    # Retained on soft-delete so a restore keeps its cover. Follow-up (#330):
    # purge the stored file during hard garbage-collection of dead sessions.
    cover_image = models.ImageField(upload_to="sessions/", blank=True)
    duration = models.CharField(
        max_length=20,
        default="",
        blank=True,
        help_text="ISO 8601 duration, e.g. PT1H30M",
    )
    # Preferences
    time_slots = models.ManyToManyField(TimeSlot, blank=True)
    # Status
    status = models.CharField(
        max_length=15,
        choices=[(item.value, item.name) for item in SessionStatus],
        default=SessionStatus.PENDING,
    )
    # Time
    creation_time = models.DateTimeField(auto_now_add=True)
    modification_time = models.DateTimeField(auto_now=True)
    # Participants
    participants_limit = models.PositiveIntegerField()
    min_age = models.PositiveIntegerField(
        default=0, help_text="Minimum age requirement (0 = no restriction)"
    )
    participants: models.ManyToManyField[User, Never] = models.ManyToManyField(
        User, through="SessionParticipation", through_fields=("session", "user")
    )
    tracks: models.ManyToManyField[Track, Never] = models.ManyToManyField(
        "Track", blank=True, related_name="sessions"
    )

    objects: ClassVar = SessionManager()
    all_objects: ClassVar = models.Manager()

    class Meta:
        db_table = "session"
        constraints = (
            models.UniqueConstraint(
                fields=["slug", "event"], name="session_unique_slug_in_event"
            ),
            models.UniqueConstraint(
                fields=["event", "ident"],
                condition=~Q(ident=""),
                name="session_unique_ident_in_event",
            ),
            models.CheckConstraint(
                condition=Q(min_age__gte=0, min_age__lte=80),
                name="session_min_age_range",
            ),
        )

    def __str__(self) -> str:
        return self.title

    @property
    def cover_image_url(self) -> str:
        return self.cover_image.url if self.cover_image else ""

    @property
    def enrolled_count(self) -> int:
        # Use cached count if available from annotation, otherwise query
        if hasattr(self, "enrolled_count_cached"):
            return cast("int", self.enrolled_count_cached)
        # CONFIRMED and OFFERED both hold a seat: an offered (but not yet
        # claimed) seat must not be handed out twice.
        return self.session_participations.filter(
            status__in=OCCUPYING_PARTICIPATION_STATUSES
        ).count()

    @property
    def waiting_count(self) -> int:
        # Use cached count if available from annotation, otherwise query
        if hasattr(self, "waiting_count_cached"):
            return cast("int", self.waiting_count_cached)
        return self.session_participations.filter(
            status=SessionParticipationStatus.WAITING
        ).count()

    @property
    def effective_participants_limit(self) -> int:
        if self.participants_limit == 0:
            return 0
        event = self.event
        if enrollment_config := event.get_most_liberal_config(self):
            return math.ceil(
                self.participants_limit * enrollment_config.percentage_slots / 100
            )
        return self.participants_limit

    @property
    def is_full(self) -> bool:
        """Check if session is at capacity for enrollment."""
        if self.participants_limit == 0:
            return False
        return self.enrolled_count >= self.effective_participants_limit

    @property
    def is_enrollment_available(self) -> bool:
        """Check if enrollment is available for this session under any active config."""
        active_configs = self.event.get_active_enrollment_configs()
        return any(config.is_session_eligible(self) for config in active_configs)

    @property
    def full_participant_info(self) -> str:  # pragma: no cover
        # TODO(@fancysnake): This is used in templates. Rewrite to pass static values
        # ZAG-16
        if self.effective_participants_limit == 0:
            base_info = str(self.enrolled_count)
        else:
            base_info = f"{self.enrolled_count}/{self.effective_participants_limit}"

            # Add session limit if different from effective limit
            if self.effective_participants_limit != self.participants_limit:
                base_info += f" (session limit: {self.participants_limit})"

        # Add waiting list info
        if self.waiting_count > 0:
            base_info += f", {self.waiting_count} waiting"

        return base_info


class AgendaItem(models.Model):
    space = models.ForeignKey(
        Space, on_delete=models.CASCADE, related_name="agenda_items"
    )
    session = models.OneToOneField(
        Session, on_delete=models.CASCADE, related_name="agenda_item"
    )
    session_confirmed = models.BooleanField(default=False)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()

    class Meta:
        db_table = "agenda_item"
        indexes: ClassVar = [
            models.Index(
                fields=["space_id", "start_time", "end_time"],
                name="agenda_item_space_time_idx",
            )
        ]
        constraints = (
            models.CheckConstraint(
                condition=(
                    Q(start_time__isnull=True)
                    | Q(end_time__isnull=True)
                    | Q(start_time__lt=F("end_time"))
                ),
                name="agenda_item_date_times",
            ),
        )

    def __str__(self) -> str:
        return (
            f"{self.session.title} by {self.session.display_name} "
            f"({self.session_confirmed})"
        )

    def overlaps_with(self, other_item: AgendaItem) -> bool:
        return bool(
            other_item.start_time
            and other_item.end_time
            and self.start_time
            and self.end_time
            and (
                (other_item.start_time <= self.start_time < other_item.end_time)
                or (other_item.start_time < self.end_time <= other_item.end_time)
            )
        )


class ProposalCategory(models.Model):
    # Owner
    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="proposal_categories"
    )
    # ID
    name = models.CharField(max_length=255)
    slug = models.SlugField()
    description = models.TextField(blank=True, default="")
    # Time
    start_time = models.DateTimeField(blank=True, null=True)
    end_time = models.DateTimeField(blank=True, null=True)
    # Settings
    max_participants_limit = models.PositiveIntegerField(default=0)
    min_participants_limit = models.PositiveIntegerField(default=0)
    durations = models.JSONField(
        default=list
    )  # ISO 8601 durations, e.g. ["PT30M", "PT1H"]
    # Waiting-list promotion behaviour for sessions in this category.
    promotion_mode = models.CharField(
        max_length=15,
        choices=[(item.value, item.name) for item in PromotionMode],
        default=PromotionMode.AUTO,
        help_text=(
            "How a freed seat is filled: AUTO promotes the next waiter straight"
            " to confirmed; OFFER_CLAIM offers the seat for a bounded window."
        ),
    )
    offer_claim_window = models.DurationField(
        default=timedelta(hours=24),
        help_text="How long an offered seat is held before it rolls to the next waiter",
    )

    class Meta:
        db_table = "proposal_category"
        constraints = (
            models.UniqueConstraint(
                fields=("slug", "event"),
                name="proposal_category_has_unique_slug_and_event",
            ),
        )

    def __str__(self) -> str:
        return f"{self.name} ({self.id})"


class SessionParticipation(models.Model):
    # Owner
    session = models.ForeignKey(
        Session, models.CASCADE, related_name="session_participations"
    )
    user = models.ForeignKey(
        User, models.CASCADE, related_name="session_participations"
    )
    # The party this seat was enrolled through; whole-party waitlist promotion
    # groups by it. Nullable: solo enrollments and pre-party rows fall back to
    # slot-owner grouping, and a deleted party must not touch seats.
    party = models.ForeignKey(
        "Party",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="session_participations",
    )
    # The account that brought an anonymous +N guest; NULL for regular
    # enrollments (people enrolled themselves or via the party flows).
    enrolled_by = models.ForeignKey(
        User, models.SET_NULL, null=True, blank=True, related_name="enrollments_made"
    )
    # Time
    creation_time = models.DateTimeField(auto_now_add=True)
    modification_time = models.DateTimeField(auto_now=True)
    # Status
    status = models.CharField(
        max_length=15,
        choices=[(item.value, item.name) for item in SessionParticipationStatus],
    )
    # Offer lifecycle (offer-and-claim mode). An OFFERED seat is held until the
    # offer is claimed or expires; a lapsed offer is terminal (the party is
    # dropped). The claim token makes the claim flow login-free for anonymous
    # waiters.
    offered_at = models.DateTimeField(null=True, blank=True)
    offer_expires_at = models.DateTimeField(null=True, blank=True)
    # A whole party shares one secret token; the index serves the login-free
    # claim lookup. Single-use is enforced by flipping status/claimed_at, not by
    # a uniqueness constraint (so all of a party's rows can carry it). Empty for
    # non-offered participations.
    claim_token = models.CharField(max_length=64, blank=True, default="", db_index=True)
    claimed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = (("session", "user"),)
        db_table = "session_participant"

    def __str__(self) -> str:
        return f"{self.user.name} {self.status} on {self.session}"


class Notification(models.Model):
    """In-app notification for a single recipient.

    Persistent, unlike flash messages. Surfaced in the navbar notifications
    dropdown and counted for the unread badge. Small and generic enough for the
    errata broadcast channel to reuse later.
    """

    recipient = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="notifications"
    )
    kind = models.CharField(
        max_length=32, choices=[(item.value, item.name) for item in NotificationKind]
    )
    # Localised, ready-to-render copy plus structured refs (session/event ids,
    # claim url, deadline). Rendered by the recipient's request, not at send.
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True, default="")
    url = models.CharField(max_length=512, blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    creation_time = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notification"
        ordering: ClassVar = ["-creation_time"]
        indexes: ClassVar = [
            # Cheap per-user unread-count query for the navbar badge.
            models.Index(
                fields=["recipient", "read_at"], name="notif_recipient_read_idx"
            )
        ]

    def __str__(self) -> str:
        return f"{self.kind} for {self.recipient.name}"

    @property
    def is_read(self) -> bool:
        return self.read_at is not None


class PersonalDataFieldType(models.TextChoices):
    TEXT = "text", "Text"
    SELECT = "select", "Select"
    CHECKBOX = "checkbox", "Checkbox"


class PersonalDataField(models.Model):
    """Defines a personal data field for an event."""

    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="personal_data_fields"
    )
    name = models.CharField(max_length=255)
    question = models.CharField(max_length=500)
    slug = models.SlugField()
    field_type = models.CharField(
        max_length=20,
        choices=PersonalDataFieldType.choices,
        default=PersonalDataFieldType.TEXT,
    )
    is_multiple = models.BooleanField(default=False)
    allow_custom = models.BooleanField(default=False)
    max_length = models.PositiveIntegerField(default=50)
    order = models.PositiveIntegerField(default=0)
    help_text = models.TextField(blank=True, default="")
    is_public = models.BooleanField(default=False)

    class Meta:
        db_table = "personal_data_field"
        ordering: ClassVar = ["order", "name"]
        constraints = (
            models.UniqueConstraint(
                fields=("event", "slug"),
                name="personal_data_field_unique_slug_per_event",
            ),
        )

    def __str__(self) -> str:
        return self.name


class PersonalDataFieldOption(models.Model):
    """An option for a select-type personal data field."""

    field = models.ForeignKey(
        PersonalDataField, on_delete=models.CASCADE, related_name="options"
    )
    label = models.CharField(max_length=255)
    value = models.CharField(max_length=255)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "personal_data_field_option"
        ordering: ClassVar = ["order", "label"]

    def __str__(self) -> str:
        return self.label


class PersonalDataFieldRequirement(models.Model):
    """Specifies which personal data fields are required for a proposal category."""

    category = models.ForeignKey(
        ProposalCategory,
        on_delete=models.CASCADE,
        related_name="personal_data_requirements",
    )
    field = models.ForeignKey(
        PersonalDataField,
        on_delete=models.CASCADE,
        related_name="category_requirements",
    )
    is_required = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "personal_data_field_requirement"
        constraints = (
            models.UniqueConstraint(
                fields=("category", "field"), name="unique_field_per_category"
            ),
        )

    def __str__(self) -> str:
        req = "required" if self.is_required else "optional"
        return f"{self.field.name} ({req}) for {self.category.name}"


class PersonalDataFieldValue(models.Model):
    """Stores personal data values for a host within an event."""

    facilitator = models.ForeignKey(
        Facilitator,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="personal_data",
    )
    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="personal_data_field_values"
    )
    field = models.ForeignKey(
        PersonalDataField, on_delete=models.CASCADE, related_name="values"
    )
    value = models.JSONField(default=str)
    creation_time = models.DateTimeField(auto_now_add=True)
    modification_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "personal_data_field_value"
        constraints = (
            models.UniqueConstraint(
                fields=("facilitator", "event", "field"),
                name="unique_personal_data_per_facilitator_event_field",
                condition=Q(facilitator__isnull=False),
            ),
        )

    def __str__(self) -> str:
        value_preview = str(self.value)[:50]
        return f"{self.field.name}: {value_preview}"


class SessionFieldType(models.TextChoices):
    TEXT = "text", "Text"
    SELECT = "select", "Select"
    CHECKBOX = "checkbox", "Checkbox"


class SessionField(models.Model):
    """Defines a session field for an event (e.g., RPG System, Genre)."""

    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="session_fields"
    )
    name = models.CharField(max_length=255)
    question = models.CharField(max_length=500)
    slug = models.SlugField()
    field_type = models.CharField(
        max_length=20, choices=SessionFieldType.choices, default=SessionFieldType.TEXT
    )
    is_multiple = models.BooleanField(default=False)
    allow_custom = models.BooleanField(default=False)
    max_length = models.PositiveIntegerField(default=50)
    order = models.PositiveIntegerField(default=0)
    help_text = models.TextField(blank=True, default="")
    icon = models.CharField(max_length=50, blank=True)
    is_public = models.BooleanField(default=False)

    class Meta:
        db_table = "session_field"
        ordering: ClassVar = ["order", "name"]
        constraints = (
            models.UniqueConstraint(
                fields=("event", "slug"), name="session_field_unique_slug_per_event"
            ),
        )

    def __str__(self) -> str:
        return self.name


class SessionFieldOption(models.Model):
    """An option for a select-type session field."""

    field = models.ForeignKey(
        SessionField, on_delete=models.CASCADE, related_name="options"
    )
    label = models.CharField(max_length=255)
    value = models.CharField(max_length=255)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "session_field_option"
        ordering: ClassVar = ["order", "label"]

    def __str__(self) -> str:
        return self.label


class SessionFieldRequirement(models.Model):
    """Specifies which session fields are required for a proposal category."""

    category = models.ForeignKey(
        ProposalCategory,
        on_delete=models.CASCADE,
        related_name="session_field_requirements",
    )
    field = models.ForeignKey(
        SessionField, on_delete=models.CASCADE, related_name="category_requirements"
    )
    is_required = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "session_field_requirement"
        constraints = (
            models.UniqueConstraint(
                fields=("category", "field"), name="unique_session_field_per_category"
            ),
        )

    def __str__(self) -> str:
        req = "required" if self.is_required else "optional"
        return f"{self.field.name} ({req}) for {self.category.name}"


class SessionFieldValue(models.Model):
    """Stores a session field value for a specific session."""

    session = models.ForeignKey(
        Session, on_delete=models.CASCADE, related_name="field_values"
    )
    field = models.ForeignKey(
        SessionField, on_delete=models.CASCADE, related_name="values"
    )
    value = models.JSONField(default=str)
    creation_time = models.DateTimeField(auto_now_add=True)
    modification_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "session_field_value"
        constraints = (
            models.UniqueConstraint(
                fields=("session", "field"),
                name="unique_session_field_value_per_session",
            ),
        )

    def __str__(self) -> str:
        value_preview = str(self.value)[:50]
        return f"{self.field.name}: {value_preview}"


class TimeSlotRequirement(models.Model):
    """Specifies which time slots are available for a proposal category."""

    category = models.ForeignKey(
        ProposalCategory,
        on_delete=models.CASCADE,
        related_name="time_slot_requirements",
    )
    time_slot = models.ForeignKey(
        TimeSlot, on_delete=models.CASCADE, related_name="category_requirements"
    )
    is_required = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "time_slot_requirement"
        constraints = (
            models.UniqueConstraint(
                fields=("category", "time_slot"), name="unique_time_slot_per_category"
            ),
        )

    def __str__(self) -> str:
        req = "required" if self.is_required else "optional"
        return f"Time slot ({req}) for {self.category.name}"


class Encounter(models.Model):
    sphere = models.ForeignKey(
        Sphere, on_delete=models.CASCADE, related_name="encounters"
    )
    creator = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="encounters"
    )
    title = models.CharField(max_length=255)
    description = models.TextField(default="", blank=True)
    game = models.CharField(max_length=255, default="", blank=True)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(blank=True, null=True)
    place = models.CharField(max_length=255, default="", blank=True)
    max_participants = models.PositiveIntegerField(default=0)
    share_code = models.CharField(max_length=6, unique=True)
    header_image = models.ImageField(upload_to="encounters/", blank=True)
    creation_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "encounter"
        constraints = (
            models.CheckConstraint(
                condition=Q(end_time__isnull=True) | Q(start_time__lt=F("end_time")),
                name="encounter_start_before_end",
            ),
        )

    def __str__(self) -> str:
        return self.title

    @property
    def header_image_url(self) -> str:
        return self.header_image.url if self.header_image else ""


class EncounterRSVP(models.Model):
    encounter = models.ForeignKey(
        Encounter, on_delete=models.CASCADE, related_name="rsvps"
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="encounter_rsvps"
    )
    ip_address = models.GenericIPAddressField()
    creation_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "encounter_rsvp"
        constraints = (
            models.UniqueConstraint(
                fields=("encounter", "user"), name="encounter_rsvp_unique_user"
            ),
        )

    def __str__(self) -> str:
        return str(self.user)


class EventSettings(models.Model):
    event = models.OneToOneField(
        Event, on_delete=models.CASCADE, related_name="settings"
    )
    displayed_session_fields = models.ManyToManyField(SessionField, blank=True)

    class Meta:
        db_table = "event_settings"

    def __str__(self) -> str:
        return f"Settings for {self.event}"


class EventPanelSettings(models.Model):
    """Organizer-only (backoffice) settings — never surfaced to attendees."""

    event = models.OneToOneField(
        Event, on_delete=models.CASCADE, related_name="panel_settings"
    )
    # Which personal-data fields show as columns on the facilitators list.
    displayed_facilitator_fields = models.ManyToManyField(PersonalDataField, blank=True)

    class Meta:
        db_table = "event_panel_settings"

    def __str__(self) -> str:
        return f"Panel settings for {self.event}"


class Track(models.Model):
    """Thematic track for organizing sessions within an event."""

    # Owner
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="tracks")
    # ID
    name = models.CharField(max_length=255)
    slug = models.SlugField()
    # Settings
    is_public = models.BooleanField(default=True)
    spaces = models.ManyToManyField(Space, blank=True, related_name="tracks")
    managers = models.ManyToManyField(User, blank=True, related_name="managed_tracks")
    # Time
    creation_time = models.DateTimeField(auto_now_add=True)
    modification_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "track"
        ordering: ClassVar = ["name"]
        constraints = (
            models.UniqueConstraint(
                fields=("event", "slug"), name="track_unique_slug_per_event"
            ),
        )

    def __str__(self) -> str:
        return self.name


class ScheduleChangeAction(models.TextChoices):
    ASSIGN = "assign", "Assign"
    UNASSIGN = "unassign", "Unassign"
    REVERT = "revert", "Revert"


class ScheduleChangeLog(models.Model):
    """Audit trail for timetable assignment changes."""

    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="schedule_change_logs"
    )
    session = models.ForeignKey(
        Session, on_delete=models.CASCADE, related_name="schedule_change_logs"
    )
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=16, choices=ScheduleChangeAction.choices)
    old_space = models.ForeignKey(
        Space,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="old_schedule_change_logs",
    )
    new_space = models.ForeignKey(
        Space,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="new_schedule_change_logs",
    )
    old_start_time = models.DateTimeField(null=True, blank=True)
    old_end_time = models.DateTimeField(null=True, blank=True)
    new_start_time = models.DateTimeField(null=True, blank=True)
    new_end_time = models.DateTimeField(null=True, blank=True)
    creation_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "schedule_change_log"
        ordering: ClassVar = ["-creation_time"]

    def __str__(self) -> str:
        return f"{self.action} {self.session} by {self.user}"


class ContentChangeLog(models.Model):
    """Audit trail for session content edits."""

    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="content_change_logs"
    )
    session = models.ForeignKey(
        Session, on_delete=models.CASCADE, related_name="content_change_logs"
    )
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    changes = models.JSONField(default=list)
    creation_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "content_change_log"
        ordering: ClassVar = ["-creation_time"]

    def __str__(self) -> str:
        return f"edit {self.session} by {self.user}"


class FacilitatorChangeLog(models.Model):
    """Audit trail for facilitator edits (accreditation + personal data)."""

    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="facilitator_change_logs"
    )
    facilitator = models.ForeignKey(
        Facilitator, on_delete=models.CASCADE, related_name="change_logs"
    )
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    changes = models.JSONField(default=list)
    creation_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "facilitator_change_log"
        ordering: ClassVar = ["-creation_time"]

    def __str__(self) -> str:
        return f"edit {self.facilitator} by {self.user}"


class Connection(models.Model):
    sphere = models.ForeignKey(
        Sphere, on_delete=models.CASCADE, related_name="connections"
    )
    display_name = models.CharField(max_length=255)
    # Encrypted secret. Write-only at the repo surface — the decrypt
    # path is owned by the import-execution slice.
    secret = models.BinaryField(default=b"")

    class Meta:
        db_table = "connection"
        constraints = (
            models.UniqueConstraint(
                fields=("sphere", "display_name"),
                name="connection_unique_display_name_per_sphere",
            ),
        )
        ordering = ("display_name",)

    def __str__(self) -> str:
        return self.display_name

    @property
    def has_secret(self) -> bool:
        return bool(self.secret)


class Discount(SoftDeleteModel):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="discounts")
    facilitator = models.ForeignKey(
        Facilitator, on_delete=models.CASCADE, related_name="discounts"
    )
    kind = models.CharField(
        max_length=10, choices=[(k.value, k.name.title()) for k in DiscountKind]
    )
    value = models.DecimalField(max_digits=10, decimal_places=2)
    note = models.CharField(max_length=255, blank=True, default="")
    creation_time = models.DateTimeField(auto_now_add=True)
    modification_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "discount"
        ordering = ("-creation_time",)
        constraints = (
            # Partial constraint: only alive (non-soft-deleted) rows count, so a
            # fresh discount can be assigned after a prior one is soft-deleted
            # without colliding with the dead row.
            models.UniqueConstraint(
                fields=("event", "facilitator"),
                condition=Q(deleted_at__isnull=True),
                name="discount_unique_alive_per_event_facilitator",
            ),
        )

    def __str__(self) -> str:
        return f"{self.facilitator} - {self.kind} {self.value}"


class Announcement(models.Model):
    sphere = models.ForeignKey(
        Sphere, on_delete=models.CASCADE, related_name="announcements"
    )
    title = models.CharField(max_length=255)
    content = models.TextField()
    is_published = models.BooleanField(default=True)
    creation_time = models.DateTimeField(auto_now_add=True)
    modification_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "announcement"
        ordering = ("-creation_time",)
        indexes = (
            models.Index(
                fields=["sphere", "is_published"], name="announcement_sphere_pub_idx"
            ),
        )

    def __str__(self) -> str:
        return self.title


class EventIntegration(models.Model):
    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="integrations"
    )
    kind = models.CharField(max_length=32)
    implementation = models.CharField(max_length=128)
    connection = models.ForeignKey(
        Connection, on_delete=models.PROTECT, related_name="event_integrations"
    )
    display_name = models.CharField(max_length=255)
    config_json = models.TextField(default="{}")
    settings_json = models.TextField(default="{}")
    questions_snapshot_json = models.TextField(default="[]")

    class Meta:
        db_table = "event_integration"
        constraints = (
            models.UniqueConstraint(
                fields=("event", "kind", "display_name"),
                name="event_integration_unique_display_name",
            ),
        )
        ordering = ("kind", "display_name")

    def __str__(self) -> str:
        return self.display_name


class ImportLogEntry(models.Model):
    integration = models.ForeignKey(
        EventIntegration, on_delete=models.CASCADE, related_name="log_entries"
    )
    row_index = models.IntegerField()
    status = models.CharField(
        max_length=16, choices=[(s.value, s.value) for s in ImportLogStatus]
    )
    reason = models.TextField(blank=True, default="")
    response_json = models.TextField(default="{}")
    title = models.CharField(max_length=255, blank=True, default="")
    display_name = models.CharField(max_length=255, blank=True, default="")
    session = models.ForeignKey(
        Session,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="import_log_entries",
    )
    attempted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "import_log_entry"
        constraints = (
            models.UniqueConstraint(
                fields=("integration", "row_index"), name="ile_unique_integration_row"
            ),
        )
        indexes = (
            models.Index(
                fields=("integration", "status", "-attempted_at"),
                name="ile_int_status_at_idx",
            ),
            models.Index(fields=("session",), name="ile_session_idx"),
        )
        ordering = ("-attempted_at", "-pk")

    def __str__(self) -> str:
        return f"{self.integration_id}/{self.row_index} {self.status}"
