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
    DASHBOARD_PAST_EVENTS,
    DASHBOARD_SPHERE_FEED,
    DASHBOARD_SPHERES_TO_DISCOVER,
    DashboardDTO,
    DashboardServiceProtocol,
    SphereEventPublishedNotification,
    SphereSubscriptionServiceProtocol,
    SphereUnsubscribeTokenPayload,
    SubscriptionAgeRestrictedError,
)

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.pacts.dashboard import (
        DashboardRepositoryProtocol,
        SphereSubscriptionNotifierProtocol,
        SphereSubscriptionRepositoryProtocol,
        SphereUnsubscribeTokenCodecProtocol,
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
            past_events=self._dashboard.list_past_events(
                user_id, now=now, limit=DASHBOARD_PAST_EVENTS
            ),
        )


class SphereSubscriptionService(SphereSubscriptionServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        subscriptions: SphereSubscriptionRepositoryProtocol,
        notifier: SphereSubscriptionNotifierProtocol,
        tokens: SphereUnsubscribeTokenCodecProtocol,
    ) -> None:
        self._transaction = transaction
        self._subscriptions = subscriptions
        self._notifier = notifier
        self._tokens = tokens

    def subscribe(self, *, sphere_id: int, user_id: int) -> None:
        with self._transaction.atomic():
            age_band = self._subscriptions.lock_subscriber_age_band(user_id)
            if not age_band.allows_optional_features:
                raise SubscriptionAgeRestrictedError
            self._subscriptions.subscribe(sphere_id=sphere_id, user_id=user_id)

    def unsubscribe(self, *, sphere_id: int, user_id: int) -> None:
        with self._transaction.atomic():
            self._subscriptions.unsubscribe(sphere_id=sphere_id, user_id=user_id)

    def read_unsubscribe_token(
        self, token: str
    ) -> SphereUnsubscribeTokenPayload | None:
        return self._tokens.loads(token)

    def unsubscribe_by_token(self, token: str) -> SphereUnsubscribeTokenPayload | None:
        if (payload := self._tokens.loads(token)) is None:
            return None
        self.unsubscribe(sphere_id=payload.sphere_id, user_id=payload.user_id)
        return payload

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
            # an event marked-but-unannounced. Recipients are read in it too,
            # so an age range changed since the listing is the one that counts.
            with self._transaction.atomic():
                self._subscriptions.mark_announced(announcement.event_pk, at=now)
                recipients = self._subscriptions.list_recipients(announcement.sphere_id)
                for recipient in recipients:
                    # NOTE: subscriptions made before age ranges existed belong
                    # to UNKNOWN accounts. They are kept, unsent, until the
                    # account confirms a range, which drops them.
                    if not recipient.age_band.allows_optional_features:
                        continue
                    self._notifier.notify_sphere_event_published(
                        SphereEventPublishedNotification(
                            recipient_user_id=recipient.user_id,
                            recipient_email=recipient.email,
                            event_name=announcement.event_name,
                            event_slug=announcement.event_slug,
                            sphere_name=announcement.sphere_name,
                            sphere_domain=announcement.sphere_domain,
                            unsubscribe_token=self._tokens.dumps(
                                SphereUnsubscribeTokenPayload(
                                    user_id=recipient.user_id,
                                    sphere_id=announcement.sphere_id,
                                    sphere_name=announcement.sphere_name,
                                )
                            ),
                        )
                    )
        return len(pending)
