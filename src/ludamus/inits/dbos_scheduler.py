"""In-system scheduler backed by DBOS: durable timers plus cron workflows.

Owns the process-wide DBOS instance (checkpointed in
``DBOS_SYSTEM_DATABASE_URL``, isolated from the application tables). Two kinds
of work live here:

- a durable per-offer timer for offer-and-claim: a checkpointed workflow sleeps
  until the offer deadline and then runs ``WaitlistPromotionService
  .expire_offer`` (behind ``OfferExpirySchedulerProtocol`` so it is swappable
  with the cron sweep);
- cron workflows for the periodic sweeps, registered as named DBOS schedules
  at launch (``DBOS.apply_schedules``), so they run in-process without
  external cron. Each tick fires once across all gunicorn workers (DBOS dedups
  on schedule name + tick in the system database).

The per-offer timers and the offers sweep intentionally coexist. The timer
hands a freed seat to the next waiting party at the exact deadline — during a
live event a popular session's seat should not idle for minutes — while the
sweep is the recovery floor for timers that were never armed (the timer is
started after commit, so a crash in between loses it) or that belonged to a
process that never came back (open-source DBOS recovers a process's own
pending workflows, not a dead peer's). Claim *correctness* depends on neither:
``claim_offer`` re-checks ``offer_expires_at`` itself.

``ServiceInjectionMiddleware`` calls ``launch_scheduler`` when a serving
process builds its handler; construction and launch stay lazy so importing
this module (or running the rest of the suite) never starts DBOS.
"""

from __future__ import annotations

import functools
import logging
import threading
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

from dbos import DBOS
from django.conf import settings
from django.db import connection, transaction
from requests import HTTPError

from ludamus.inits.builders import build_announcement_fanout, build_waitlist_promotion
from ludamus.inits.config import SchedulerMode, scheduler_mode
from ludamus.inits.parley import (
    DisabledParleyMembershipOutbox,
    DisabledParleyRevocationOutbox,
    DisabledStaffThread,
    InlineParleyMembershipOutbox,
    InlineParleyRevocationOutbox,
    InlineStaffThread,
    deliver_membership,
    deliver_revocations,
    deliver_thread_post,
)
from ludamus.links.scheduler import CronSweepAnnouncementFanout, CronSweepOfferScheduler
from ludamus.pacts.staff_cases import StaffThreadEntry

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from ludamus.pacts.enrollment import OfferExpirySchedulerProtocol
    from ludamus.pacts.notifications import AnnouncementFanoutSchedulerProtocol
    from ludamus.pacts.parley import (
        ParleyMembershipOutboxProtocol,
        ParleyRevocationOutboxProtocol,
    )
    from ludamus.pacts.staff_cases import StaffThreadProtocol
    from ludamus.pacts.sweeps import Sweep

logger = logging.getLogger(__name__)

_launched = threading.Event()
_launch_lock = threading.Lock()


def _releases_db_connection[**P](step: Callable[P, None]) -> Callable[P, None]:
    # NOTE: DBOS runs steps on its own long-lived threads, where Django's
    # request signals never fire, so each thread would hold an idle Postgres
    # connection forever.
    @functools.wraps(step)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> None:
        try:
            step(*args, **kwargs)
        finally:
            connection.close()

    return wrapper


@DBOS.step()
@_releases_db_connection
def _expire_offer_step(participation_id: int) -> None:
    # Re-offers produced by the expiry stay durable by reusing this scheduler.
    build_waitlist_promotion(DBOSOfferExpiryScheduler()).expire_offer(
        participation_id=participation_id
    )


@DBOS.workflow()
def _expire_offer_workflow(participation_id: int, delay_seconds: float) -> None:
    DBOS.sleep(delay_seconds)
    _expire_offer_step(participation_id)


@DBOS.step()
@_releases_db_connection
def _fanout_announcement_step(announcement_id: int) -> None:
    notified = build_announcement_fanout().fanout(announcement_id)
    logger.info(
        "announcement fanout: announcement=%s notified %s subscriber(s)",
        announcement_id,
        notified,
    )


@DBOS.workflow()
def _fanout_announcement_workflow(announcement_id: int) -> None:
    _fanout_announcement_step(announcement_id)


_cron_workflows: list[tuple[Callable[[datetime, None], None], Sweep]] = []


def _cron_workflow(sweep: Sweep) -> Callable[[datetime, None], None]:
    @DBOS.step(name=f"{sweep.workflow}_step")
    @_releases_db_connection
    def step(now: datetime) -> None:
        logger.info("%s", sweep.summary(sweep.run(now)))

    @DBOS.workflow(name=sweep.workflow)
    def workflow(scheduled: datetime, _context: None) -> None:
        step(scheduled)

    return workflow


def register_sweeps(sweeps: Iterable[Sweep]) -> None:
    # Registered under the sweep's own names: DBOS recovers and schedules by
    # name, so each workflow must exist in every process before launch, under
    # the name the system database already holds.
    _cron_workflows.extend((_cron_workflow(sweep), sweep) for sweep in sweeps)


def _worth_retrying(error: BaseException) -> bool:
    # A refused signature or claim is refused again; the Worker being away
    # or failing is what a retry waits out.
    response = error.response if isinstance(error, HTTPError) else None
    return response is None or response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR


# 12 attempts doubling from 2 s keep trying for about an hour, well inside
# the pass lifetime, past which the revocation would be moot anyway.
@DBOS.step(
    retries_allowed=True,
    max_attempts=12,
    interval_seconds=2,
    backoff_rate=2,
    should_retry=_worth_retrying,
)
def _deliver_parley_revocation_step(sphere_id: int, subject: str) -> None:
    deliver_revocations(sphere_ids=[sphere_id], subject=subject)


@DBOS.workflow()
def _parley_revocation_workflow(sphere_ids: list[int], subject: str) -> None:
    for sphere_id in sphere_ids:
        _deliver_parley_revocation_step(sphere_id, subject)


@DBOS.step(
    retries_allowed=True,
    max_attempts=12,
    interval_seconds=2,
    backoff_rate=2,
    should_retry=_worth_retrying,
)
@_releases_db_connection
def _deliver_parley_membership_step(conversation_id: int) -> None:
    deliver_membership(conversation_id)


@DBOS.workflow()
def _parley_membership_workflow(conversation_ids: list[int]) -> None:
    for conversation_id in conversation_ids:
        _deliver_parley_membership_step(conversation_id)


@DBOS.step(
    retries_allowed=True,
    max_attempts=12,
    interval_seconds=2,
    backoff_rate=2,
    should_retry=_worth_retrying,
)
def _deliver_staff_thread_step(entry_json: str) -> None:
    deliver_thread_post(StaffThreadEntry.model_validate_json(entry_json))


@DBOS.workflow()
def _staff_thread_workflow(entry_json: str) -> None:
    _deliver_staff_thread_step(entry_json)


def _apply_schedules() -> None:
    # Upsert by name, so every launch (and every worker) converges on the same
    # definitions; cadence edits in `inits.sweeps` take effect on the next launch.
    DBOS.apply_schedules(
        [
            {
                "schedule_name": sweep.workflow,
                "workflow_fn": workflow,
                "schedule": sweep.cron,
            }
            for workflow, sweep in _cron_workflows
        ]
    )


def _ensure_launched() -> None:
    if _launched.is_set():
        return
    with _launch_lock:  # double-checked so concurrent requests launch DBOS once
        if _launched.is_set():
            return
        DBOS(
            config={
                "name": "ludamus",
                "system_database_url": settings.DBOS_SYSTEM_DATABASE_URL,
                # Per gunicorn worker; the default 20 exhausts Postgres slots.
                "sys_db_pool_size": 2,
            }
        )
        DBOS.launch()
        _apply_schedules()
        _launched.set()
        logger.info(
            "DBOS launched; schedules active: %s",
            [sweep.workflow for _workflow, sweep in _cron_workflows],
        )


def launch_scheduler() -> None:
    # Called when a serving process builds its handler (per gunicorn worker,
    # post-fork) so the cron workflows run without waiting for traffic. Launch
    # runs on a daemon thread: it does IO (system-schema migration), and a
    # failure there must not take request serving down — the thread dies loudly
    # via threading.excepthook while the management commands remain the manual
    # floor. The next schedule_expiry call retries the launch.
    if scheduler_mode() is not SchedulerMode.DBOS:
        return
    threading.Thread(target=_ensure_launched, name="dbos-launch", daemon=True).start()


class DBOSOfferExpiryScheduler:
    @staticmethod
    def schedule_expiry(*, participation_id: int, run_at: datetime) -> None:
        _ensure_launched()
        delay = max(0.0, (run_at - datetime.now(UTC)).total_seconds())
        DBOS.start_workflow(_expire_offer_workflow, participation_id, delay)


class DBOSAnnouncementFanoutScheduler:
    @staticmethod
    def schedule_fanout(*, announcement_id: int) -> None:
        _ensure_launched()
        # ATOMIC_REQUESTS holds the announcement row uncommitted until the
        # request ends; a zero-delay workflow started now would race the commit
        # and find nothing to claim. After commit the row is visible; a crash
        # in between loses only the trigger, and the sweep recovers it.
        transaction.on_commit(
            lambda: DBOS.start_workflow(_fanout_announcement_workflow, announcement_id)
        )


def offer_expiry_scheduler() -> OfferExpirySchedulerProtocol:
    if scheduler_mode() is SchedulerMode.DBOS:
        return DBOSOfferExpiryScheduler()
    return CronSweepOfferScheduler()


def announcement_fanout_scheduler() -> AnnouncementFanoutSchedulerProtocol:
    if scheduler_mode() is SchedulerMode.DBOS:
        return DBOSAnnouncementFanoutScheduler()
    return CronSweepAnnouncementFanout()


class DBOSParleyRevocationOutbox:
    @staticmethod
    def schedule(*, sphere_ids: list[int], subject: str) -> None:
        _ensure_launched()
        transaction.on_commit(
            lambda: DBOS.start_workflow(
                _parley_revocation_workflow, sphere_ids, subject
            )
        )


def parley_revocation_outbox() -> ParleyRevocationOutboxProtocol:
    agent_host: str = settings.PARLEY_AGENT_HOST
    private_key: str = settings.PARLEY_SIGNING_PRIVATE_KEY
    if not (agent_host and private_key):
        return DisabledParleyRevocationOutbox()
    if scheduler_mode() is SchedulerMode.DBOS:
        return DBOSParleyRevocationOutbox()
    return InlineParleyRevocationOutbox()


class DBOSParleyMembershipOutbox:
    @staticmethod
    def schedule(*, conversation_ids: list[int]) -> None:
        if not conversation_ids:
            return
        _ensure_launched()
        transaction.on_commit(
            lambda: DBOS.start_workflow(_parley_membership_workflow, conversation_ids)
        )


def parley_membership_outbox() -> ParleyMembershipOutboxProtocol:
    agent_host: str = settings.PARLEY_AGENT_HOST
    private_key: str = settings.PARLEY_SIGNING_PRIVATE_KEY
    if not (agent_host and private_key):
        return DisabledParleyMembershipOutbox()
    if scheduler_mode() is SchedulerMode.DBOS:
        return DBOSParleyMembershipOutbox()
    return InlineParleyMembershipOutbox()


class DBOSStaffThread:
    """Posts into a case's thread after commit, retrying while the chat is away."""

    @staticmethod
    def post(entry: StaffThreadEntry) -> None:
        _ensure_launched()
        payload = entry.model_dump_json()
        transaction.on_commit(
            lambda: DBOS.start_workflow(_staff_thread_workflow, payload)
        )


def staff_thread() -> StaffThreadProtocol:
    agent_host: str = settings.PARLEY_AGENT_HOST
    private_key: str = settings.PARLEY_SIGNING_PRIVATE_KEY
    if not (agent_host and private_key):
        return DisabledStaffThread()
    if scheduler_mode() is SchedulerMode.DBOS:
        return DBOSStaffThread()
    return InlineStaffThread()
