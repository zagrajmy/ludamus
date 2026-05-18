from __future__ import annotations

import math
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar, Never, cast

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
    SessionParticipationStatus,
    SessionStatus,
    SpherePage,
    UserType,
    VirtualEnrollmentConfig,
)

if TYPE_CHECKING:
    from collections.abc import Collection

    from ludamus.pacts import EventDTO, UserDTO


MAX_SLUG_RETRIES = 10
RANDOM_SLUG_BYTES = 7  # 10 characters
DEFAULT_NAME = "Andrzej"
MAX_CONNECTED_USERS = 6  # Maximum number of connected users per manager


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
    manager = models.ForeignKey(
        "User",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="connected",
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

    objects = UserManager()

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>"

    def get_full_name(self) -> str:
        return self.name or DEFAULT_NAME

    @property
    def full_name(self) -> str:
        return self.get_full_name()

    @property
    def initials(self) -> str:
        """Return user initials (first letter of each word in name)."""
        name = self.name or self.username or ""
        return "".join(word[0].upper() for word in name.split() if word)[:2] or "?"

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


class Sphere(models.Model):
    """Big group for whole provinces, topics, organizations or big events."""

    name = models.CharField(max_length=255)
    site = models.OneToOneField(Site, on_delete=models.PROTECT, related_name="sphere")
    managers = models.ManyToManyField(User)
    enabled_pages = models.JSONField(
        default=SpherePage.all_values,
        help_text="List of enabled page identifiers, e.g. ['events', 'encounters']",
    )
    default_page = models.CharField(
        max_length=20,
        choices=[(p.value, p.name.title()) for p in SpherePage],
        default=SpherePage.EVENTS,
    )

    class Meta:
        db_table = "sphere"

    def __str__(self) -> str:
        return self.name


class Event(models.Model):
    # Owner
    sphere = models.ForeignKey(Sphere, on_delete=models.CASCADE, related_name="events")
    # ID
    name = models.CharField(max_length=255)
    slug = models.SlugField()
    description = models.TextField(default="", blank=True)
    # Time - start and end
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    # Publication time
    publication_time = models.DateTimeField(blank=True, null=True)
    # Proposal times
    proposal_start_time = models.DateTimeField(blank=True, null=True)
    proposal_end_time = models.DateTimeField(blank=True, null=True)
    # Filterable tag categories for session list
    filterable_tag_categories: models.ManyToManyField[TagCategory, Never] = (
        models.ManyToManyField(
            "TagCategory",
            blank=True,
            help_text="Tag categories that will appear as filters in the session list",
        )
    )

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
    """Bookable room/location within an area."""

    HIERARCHICAL_ORDER: ClassVar = (
        "area__venue__order",
        "area__venue__name",
        "area__order",
        "area__name",
        "order",
        "name",
    )

    # Owner - spaces belong to an area
    area = models.ForeignKey("Area", on_delete=models.CASCADE, related_name="spaces")
    # ID
    name = models.CharField(max_length=255)
    slug = models.SlugField()
    # Details
    capacity = models.PositiveIntegerField(null=True, blank=True)
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
                fields=("slug", "area"), name="space_has_unique_slug_and_area"
            ),
        )

    def __str__(self) -> str:
        return f"{self.area.venue.name} > {self.area.name} > {self.name}"


class Venue(models.Model):
    """Physical location/building for an event."""

    # Owner - venues belong to an event
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="venues")
    # ID
    name = models.CharField(max_length=255)
    slug = models.SlugField()
    # Details
    address = models.TextField(blank=True, default="")
    # Ordering
    order = models.PositiveIntegerField(default=0)
    # Time
    creation_time = models.DateTimeField(auto_now_add=True)
    modification_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "venue"
        ordering: ClassVar = ["order", "name"]
        constraints = (
            models.UniqueConstraint(
                fields=("slug", "event"), name="venue_has_unique_slug_and_event"
            ),
        )

    def __str__(self) -> str:
        return self.name


class Area(models.Model):
    """Subdivision within a venue (floor, wing, section)."""

    # Owner - areas belong to a venue
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="areas")
    # ID
    name = models.CharField(max_length=255)
    slug = models.SlugField()
    # Details
    description = models.TextField(blank=True, default="")
    # Ordering
    order = models.PositiveIntegerField(default=0)
    # Time
    creation_time = models.DateTimeField(auto_now_add=True)
    modification_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "area"
        ordering: ClassVar = ["order", "name"]
        constraints = (
            models.UniqueConstraint(
                fields=("slug", "venue"), name="area_has_unique_slug_and_venue"
            ),
        )

    def __str__(self) -> str:
        return f"{self.venue.name} > {self.name}"


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


class TagCategory(models.Model):
    class InputType(models.TextChoices):  # pylint: disable=too-many-ancestors
        SELECT = "select", _("Select from list")
        TYPE = "type", _("Type comma-separated")

    name = models.CharField(max_length=255)
    icon = models.CharField(
        max_length=50,
        blank=True,
        help_text="Heroicon name (e.g., 'puzzle-piece', 'star', 'heart')",
    )
    input_type = models.CharField(
        max_length=10, choices=InputType.choices, default=InputType.SELECT
    )

    class Meta:
        db_table = "tag_category"

    def __str__(self) -> str:
        return self.name


class Tag(models.Model):
    name = models.CharField(max_length=255)
    category = models.ForeignKey(
        TagCategory, on_delete=models.CASCADE, related_name="tags"
    )
    confirmed = models.BooleanField(default=False)

    class Meta:
        db_table = "tag"
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["name", "category"], name="unique_tag_name_per_category"
            )
        ]

    def __str__(self) -> str:
        return self.name


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


class SessionManager(models.Manager["Session"]):
    def has_conflicts(self, session: Session, user: UserDTO) -> bool:
        return (
            self.get_queryset()
            .filter(
                agenda_item__space__area__venue__event=session.agenda_item.space.area.venue.event,
                session_participations__user_id=user.pk,
                session_participations__status=SessionParticipationStatus.CONFIRMED,
            )
            .filter(
                Q(
                    agenda_item__start_time__gte=session.agenda_item.start_time,
                    agenda_item__start_time__lt=session.agenda_item.end_time,
                )
                | Q(
                    agenda_item__end_time__gt=session.agenda_item.start_time,
                    agenda_item__end_time__lte=session.agenda_item.end_time,
                )
            )
            .exclude(id=session.id)
            .exists()
        )


class Session(models.Model):
    """Session model."""

    # Owner
    sphere = models.ForeignKey(
        "Sphere", on_delete=models.CASCADE, related_name="sessions"
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
    description = models.TextField(default="", blank=True)
    requirements = models.TextField(blank=True)
    needs = models.TextField(default="", blank=True)
    duration = models.CharField(
        max_length=20,
        default="",
        blank=True,
        help_text="ISO 8601 duration, e.g. PT1H30M",
    )
    tags = models.ManyToManyField(Tag, blank=True)
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
        User, through="SessionParticipation"
    )
    tracks: models.ManyToManyField[Track, Never] = models.ManyToManyField(
        "Track", blank=True, related_name="sessions"
    )

    objects = SessionManager()

    class Meta:
        db_table = "session"
        constraints = (
            models.UniqueConstraint(
                fields=["slug", "sphere"], name="session_unique_slug_in_sphere"
            ),
            models.CheckConstraint(
                condition=Q(min_age__gte=0, min_age__lte=18),
                name="session_min_age_range",
            ),
        )

    def __str__(self) -> str:
        return self.title

    @property
    def enrolled_count(self) -> int:
        # Use cached count if available from annotation, otherwise query
        if hasattr(self, "enrolled_count_cached"):
            return cast("int", self.enrolled_count_cached)
        return self.session_participations.filter(
            status=SessionParticipationStatus.CONFIRMED
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
        """Get effective participants limit considering enrollment config percentage."""
        if self.participants_limit == 0:
            return 0
        event = self.agenda_item.space.area.venue.event
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
        active_configs = (
            self.agenda_item.space.area.venue.event.get_active_enrollment_configs()
        )
        return any(config.is_session_eligible(self) for config in active_configs)

    @property
    def full_participant_info(self) -> str:  # pragma: no cover
        """Get complete participant information display."""
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
    tag_categories = models.ManyToManyField(TagCategory)
    max_participants_limit = models.PositiveIntegerField(default=0)
    min_participants_limit = models.PositiveIntegerField(default=0)
    durations = models.JSONField(
        default=list
    )  # ISO 8601 durations, e.g. ["PT30M", "PT1H"]

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
    # Time
    creation_time = models.DateTimeField(auto_now_add=True)
    modification_time = models.DateTimeField(auto_now=True)
    # Status
    status = models.CharField(
        max_length=15,
        choices=[(item.value, item.name) for item in SessionParticipationStatus],
    )

    class Meta:
        unique_together = (("session", "user"),)
        db_table = "session_participant"

    def __str__(self) -> str:
        return f"{self.user.name} {self.status} on {self.session}"


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


class HostPersonalData(models.Model):
    """Stores personal data values for a host within an event."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="personal_data",
    )
    facilitator = models.ForeignKey(
        Facilitator,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="personal_data",
    )
    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="host_personal_data"
    )
    field = models.ForeignKey(
        PersonalDataField, on_delete=models.CASCADE, related_name="values"
    )
    value = models.JSONField(default=str)
    creation_time = models.DateTimeField(auto_now_add=True)
    modification_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "host_personal_data"
        constraints = (
            models.UniqueConstraint(
                fields=("user", "event", "field"),
                name="unique_personal_data_per_user_event_field",
                condition=Q(user__isnull=False),
            ),
            models.UniqueConstraint(
                fields=("facilitator", "event", "field"),
                name="unique_personal_data_per_facilitator_event_field",
                condition=Q(facilitator__isnull=False),
            ),
            models.CheckConstraint(
                condition=Q(user__isnull=False) | Q(facilitator__isnull=False),
                name="personal_data_requires_owner",
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


def can_enroll_users(
    *,
    users: list[UserDTO],
    event: EventDTO,
    virtual_config: VirtualEnrollmentConfig,
    users_to_enroll: list[UserDTO],
) -> bool:
    # Get currently enrolled users
    currently_enrolled = set(
        SessionParticipation.objects.filter(
            status=SessionParticipationStatus.CONFIRMED,
            user_id__in=[u.pk for u in users],
            session__agenda_item__space__area__venue__event_id=event.pk,
        )
        .values_list("user_id", flat=True)
        .distinct()
    )

    # Add new users to enroll
    users_to_enroll_ids = {u.pk for u in users_to_enroll}
    total_enrolled = currently_enrolled | users_to_enroll_ids

    return len(total_enrolled) <= virtual_config.allowed_slots


def get_used_slots(users: list[UserDTO], event: EventDTO) -> int:
    # Count unique users who have at least one confirmed enrollment
    return len(
        SessionParticipation.objects.filter(
            status=SessionParticipationStatus.CONFIRMED,
            user_id__in=[u.pk for u in users],
            session__agenda_item__space__area__venue__event_id=event.pk,
        )
        .values_list("user", flat=True)
        .distinct()
    )


def get_vc_available_slots(
    *, users: list[UserDTO], event: EventDTO, virtual_config: VirtualEnrollmentConfig
) -> int:
    return max(
        0, virtual_config.allowed_slots - get_used_slots(users=users, event=event)
    )


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
