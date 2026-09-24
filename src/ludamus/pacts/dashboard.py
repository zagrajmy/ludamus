"""The signed-in home on the root sphere: what you hold, and what is open.

The dashboard reads across every sphere at once, so its DTOs carry absolute
URLs and the sphere each row came from — a relative ``{% url %}`` would point
at whichever domain happens to be rendering.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum, auto
from typing import Protocol

from pydantic import BaseModel

# How much of each section a dashboard holds before it stops being a glance.
# The agenda is uncapped: it is what this member already committed to, and
# hiding part of that is worse than a long column.
DASHBOARD_SPHERE_FEED = 12
DASHBOARD_OPEN_ENCOUNTERS = 8
DASHBOARD_SPHERES_TO_DISCOVER = 6


class DashboardRole(StrEnum):
    """Why a row is on this dashboard — the template's one branch."""

    SIGNED_UP = auto()
    ORGANIZING = auto()
    OPEN = auto()


class DashboardCardDTO(BaseModel):
    """One dated thing on the dashboard — a programme item or an encounter."""

    title: str
    url: str
    start_time: datetime
    # The event or sphere this came out of — what a reader needs to place it.
    origin_name: str
    role: DashboardRole
    cover_url: str = ""
    place: str = ""
    attending_count: int = 0
    # 0 when the thing takes anyone, like a talk with no seat limit.
    capacity: int = 0

    @property
    def spots_remaining(self) -> int | None:
        return max(0, self.capacity - self.attending_count) if self.capacity else None


class DashboardSphereDTO(BaseModel):
    pk: int
    name: str
    url: str
    logo_url: str = ""
    upcoming_count: int = 0
    # The button is a toggle, so a sphere stays listed once you follow it —
    # otherwise subscribing would hide the only control that undoes it.
    is_subscribed: bool = False


class DashboardDTO(BaseModel):
    # What this member holds, soonest first.
    agenda: list[DashboardCardDTO]
    # Open encounters anyone may join, across every sphere.
    open_encounters: list[DashboardCardDTO]
    # What is coming up where this member already plays, minus their own rows.
    sphere_feed: list[DashboardCardDTO]
    discover: list[DashboardSphereDTO]


class SubscriptionRecipientDTO(BaseModel):
    user_id: int
    email: str


class SphereEventAnnouncementDTO(BaseModel):
    event_pk: int
    event_name: str
    event_slug: str
    sphere_name: str
    # Site domain of the owning sphere — the notifier composes the absolute
    # event link from it, the same as the printables reminder does.
    sphere_domain: str
    recipients: list[SubscriptionRecipientDTO]


class SphereEventPublishedNotification(BaseModel):
    recipient_user_id: int
    recipient_email: str
    event_name: str
    event_slug: str
    sphere_name: str
    sphere_domain: str


class DashboardRepositoryProtocol(Protocol):
    @staticmethod
    def list_agenda(user_id: int, *, now: datetime) -> list[DashboardCardDTO]: ...
    @staticmethod
    def list_open_encounters(
        user_id: int, *, now: datetime, limit: int
    ) -> list[DashboardCardDTO]: ...
    @staticmethod
    def list_sphere_feed(
        user_id: int, *, now: datetime, limit: int
    ) -> list[DashboardCardDTO]: ...
    @staticmethod
    def list_spheres_to_discover(
        user_id: int, *, now: datetime, limit: int
    ) -> list[DashboardSphereDTO]: ...


class SphereSubscriptionRepositoryProtocol(Protocol):
    @staticmethod
    def subscribe(*, sphere_id: int, user_id: int) -> None: ...
    @staticmethod
    def unsubscribe(*, sphere_id: int, user_id: int) -> None: ...
    @staticmethod
    def list_pending_announcements(
        *, now: datetime
    ) -> list[SphereEventAnnouncementDTO]: ...
    @staticmethod
    def mark_announced(event_pk: int, *, at: datetime) -> None: ...


class SphereSubscriptionNotifierProtocol(Protocol):
    def notify_sphere_event_published(
        self, notification: SphereEventPublishedNotification
    ) -> None: ...


class DashboardServiceProtocol(Protocol):
    def read(self, *, user_id: int, now: datetime) -> DashboardDTO: ...


class SphereSubscriptionServiceProtocol(Protocol):
    def subscribe(self, *, sphere_id: int, user_id: int) -> None: ...
    def unsubscribe(self, *, sphere_id: int, user_id: int) -> None: ...
    def announce_published_events(self, *, now: datetime) -> int: ...
