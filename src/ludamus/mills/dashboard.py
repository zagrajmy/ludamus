"""The signed-in home on the root sphere, and the sphere subscriptions behind it.

`DashboardService` composes one read of what a member holds and what is open
to them across every sphere. `SphereSubscriptionService` owns the other half
of the subscribe button: the sweep that tells subscribers when a sphere
publishes an event.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts.dashboard import (
    DASHBOARD_OPEN_ENCOUNTERS,
    DASHBOARD_SPHERE_FEED,
    DASHBOARD_SPHERES_TO_DISCOVER,
    DashboardDTO,
    DashboardServiceProtocol,
    SphereEventPublishedNotification,
    SphereSubscriptionServiceProtocol,
)

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.pacts.dashboard import (
        DashboardRepositoryProtocol,
        SphereSubscriptionNotifierProtocol,
        SphereSubscriptionRepositoryProtocol,
    )
    from ludamus.pacts.services import TransactionProtocol


class DashboardService(DashboardServiceProtocol):
    def __init__(self, dashboard: DashboardRepositoryProtocol) -> None:
        self._dashboard = dashboard

    def read(self, *, user_id: int, now: datetime) -> DashboardDTO:
        return DashboardDTO(
            agenda=self._dashboard.list_agenda(user_id, now=now),
            open_encounters=self._dashboard.list_open_encounters(
                user_id, now=now, limit=DASHBOARD_OPEN_ENCOUNTERS
            ),
            sphere_feed=self._dashboard.list_sphere_feed(
                user_id, now=now, limit=DASHBOARD_SPHERE_FEED
            ),
            discover=self._dashboard.list_spheres_to_discover(
                user_id, now=now, limit=DASHBOARD_SPHERES_TO_DISCOVER
            ),
        )


class SphereSubscriptionService(SphereSubscriptionServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        subscriptions: SphereSubscriptionRepositoryProtocol,
        notifier: SphereSubscriptionNotifierProtocol,
    ) -> None:
        self._transaction = transaction
        self._subscriptions = subscriptions
        self._notifier = notifier

    def subscribe(self, *, sphere_id: int, user_id: int) -> None:
        with self._transaction.atomic():
            self._subscriptions.subscribe(sphere_id=sphere_id, user_id=user_id)

    def unsubscribe(self, *, sphere_id: int, user_id: int) -> None:
        with self._transaction.atomic():
            self._subscriptions.unsubscribe(sphere_id=sphere_id, user_id=user_id)

    def announce_published_events(self, *, now: datetime) -> int:
        """Tell each sphere's subscribers about the events it just published.

        Returns:
            How many events were announced. Safe to run repeatedly: an event
            is stamped the first time it goes out, and only then.
        """
        pending = self._subscriptions.list_pending_announcements(now=now)
        for announcement in pending:
            # Stamped in the same transaction as the notifications, the way
            # the printables sweep does it, so a crash mid-batch never leaves
            # an event marked-but-unannounced.
            with self._transaction.atomic():
                self._subscriptions.mark_announced(announcement.event_pk, at=now)
                for recipient in announcement.recipients:
                    self._notifier.notify_sphere_event_published(
                        SphereEventPublishedNotification(
                            recipient_user_id=recipient.user_id,
                            recipient_email=recipient.email,
                            event_name=announcement.event_name,
                            event_slug=announcement.event_slug,
                            sphere_name=announcement.sphere_name,
                            sphere_domain=announcement.sphere_domain,
                        )
                    )
        return len(pending)
