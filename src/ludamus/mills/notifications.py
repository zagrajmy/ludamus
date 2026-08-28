"""Notifications: the navbar bell read path, subscriptions, announcement fanout."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts.legacy import NotFoundError
from ludamus.pacts.notifications import (
    AnnouncementFanoutServiceProtocol,
    NavbarNotificationsDTO,
    NotificationsServiceProtocol,
    NotificationSubscriptionsServiceProtocol,
    SubscriptionGroupDTO,
    SubscriptionSource,
)

if TYPE_CHECKING:
    from ludamus.pacts.notifications import (
        AnnouncementFanoutRepositoryProtocol,
        NotificationDTO,
        NotificationReadRepositoryProtocol,
        NotificationSubscriptionRepositoryProtocol,
        SubscriptionDTO,
    )
    from ludamus.pacts.services import TransactionProtocol

NAVBAR_LIMIT = 10


class NotificationsService(NotificationsServiceProtocol):
    def __init__(
        self,
        transaction: TransactionProtocol,
        notifications: NotificationReadRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._notifications = notifications

    def get_navbar(self, user_id: int) -> NavbarNotificationsDTO:
        return NavbarNotificationsDTO(
            unread_count=self._notifications.unread_count(user_id),
            items=self._notifications.list_for_user(user_id, limit=NAVBAR_LIMIT),
        )

    def total_count(self, user_id: int) -> int:
        return self._notifications.total_count(user_id)

    def list_for_user(
        self, user_id: int, *, limit: int, offset: int = 0
    ) -> list[NotificationDTO]:
        return self._notifications.list_for_user(user_id, limit=limit, offset=offset)

    def mark_read(self, user_id: int, pk: int) -> NotificationDTO | None:
        with self._transaction.atomic():
            return self._notifications.mark_read(user_id, pk)

    def mark_all_read(self, user_id: int) -> None:
        with self._transaction.atomic():
            self._notifications.mark_all_read(user_id)


class NotificationSubscriptionsService(NotificationSubscriptionsServiceProtocol):
    def __init__(
        self,
        transaction: TransactionProtocol,
        subscriptions: NotificationSubscriptionRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._subscriptions = subscriptions

    def subscribe_sphere_visit(self, *, user_id: int, sphere_id: int) -> None:
        with self._transaction.atomic():
            self._subscriptions.ensure_sphere(
                user_id=user_id, sphere_id=sphere_id, source=SubscriptionSource.VISIT
            )

    def subscribe_enrollments(self, *, user_ids: list[int], event_id: int) -> None:
        if not user_ids:
            return
        with self._transaction.atomic():
            self._subscriptions.ensure_events(
                user_ids=user_ids,
                event_id=event_id,
                source=SubscriptionSource.ENROLLMENT,
            )

    def list_grouped(self, user_id: int) -> list[SubscriptionGroupDTO]:
        sphere_names: dict[int, str] = {}
        sphere_subs: dict[int, SubscriptionDTO] = {}
        event_subs: dict[int, list[SubscriptionDTO]] = {}
        for subscription in self._subscriptions.list_for_user(user_id):
            sphere_names[subscription.parent_sphere_id] = (
                subscription.parent_sphere_name
            )
            if subscription.sphere_id is not None:
                sphere_subs[subscription.parent_sphere_id] = subscription
            else:
                event_subs.setdefault(subscription.parent_sphere_id, []).append(
                    subscription
                )
        groups = [
            SubscriptionGroupDTO(
                sphere_name=name,
                sphere_subscription=sphere_subs.get(sphere_id),
                events=sorted(event_subs.get(sphere_id, []), key=_subscription_label),
            )
            for sphere_id, name in sphere_names.items()
        ]
        return sorted(groups, key=_group_name)

    def set_muted(self, *, user_id: int, pk: int, muted: bool) -> None:
        with self._transaction.atomic():
            if not self._subscriptions.set_muted(user_id=user_id, pk=pk, muted=muted):
                raise NotFoundError


def _subscription_label(subscription: SubscriptionDTO) -> str:
    return subscription.label.casefold()


def _group_name(group: SubscriptionGroupDTO) -> str:
    return group.sphere_name.casefold()


class AnnouncementFanoutService(AnnouncementFanoutServiceProtocol):
    def __init__(
        self,
        transaction: TransactionProtocol,
        announcements: AnnouncementFanoutRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._announcements = announcements

    def fanout(self, announcement_id: int) -> int:
        # Claim and notification rows share one transaction: a crash mid-fanout
        # rolls the claim back, so the recovery sweep retries the whole batch —
        # subscribers get the announcement once or, transiently, not yet; never
        # twice.
        with self._transaction.atomic():
            if (claimed := self._announcements.claim(announcement_id)) is None:
                return 0
            return self._announcements.create_announcement_notifications(
                recipient_ids=self._announcements.active_sphere_subscriber_ids(
                    claimed.sphere_id
                ),
                announcement=claimed,
            )

    def fanout_due(self) -> int:
        return sum(
            self.fanout(announcement_id)
            for announcement_id in self._announcements.due_ids()
        )
