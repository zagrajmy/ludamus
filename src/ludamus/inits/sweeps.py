"""Every periodic sweep, once: what runs, on which cron, and how it reads.

The DBOS schedule (`inits.dbos_scheduler`) and the management commands
(`gates.cli`) both run these rows; `InitsConfig.ready()` hands the table to
each. Cron cadences use croniter syntax, in UTC.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.inits.builders import (
    build_announcement_fanout,
    build_email_verification,
    build_encounter_guests,
    build_encounters,
    build_konwencik_export,
    build_listings,
    build_printables_reminder,
    build_sites,
    build_sphere_subscriptions,
    build_waitlist_promotion,
)
from ludamus.inits.dbos_scheduler import offer_expiry_scheduler
from ludamus.pacts.sweeps import Sweep

if TYPE_CHECKING:
    from datetime import datetime


def _expire_lapsed_offers(now: datetime) -> int:
    service = build_waitlist_promotion(offer_expiry_scheduler())
    return service.expire_lapsed_offers(now=now)


def _purge_stale_invitees(now: datetime) -> int:
    sites = build_sites()
    encounters = build_encounters(sites, build_encounter_guests(sites))
    return encounters.purge_stale_invitees(now=now)


SWEEPS = (
    # The recovery floor under the per-offer DBOS timers: it catches the timers
    # that were never armed or died with their process.
    Sweep(
        command="expire_offers",
        workflow="expire_offers_sweep",
        cron="*/5 * * * *",
        run=_expire_lapsed_offers,
        report="Processed {handled} lapsed offer(s).",
    ),
    # Each morning, Polish time being UTC+1/+2.
    Sweep(
        command="send_printables_reminders",
        workflow="printables_reminders_tick",
        cron="0 7 * * *",
        run=lambda now: build_printables_reminder().send_due_reminders(now=now),
        report="Sent printables reminders for {handled} event(s).",
    ),
    Sweep(
        command="send_verification_reminders",
        workflow="verification_reminders_tick",
        cron="30 7 * * *",
        run=lambda now: build_email_verification().send_due_reminders(now=now),
        report="Sent verification reminders to {handled} user(s).",
    ),
    # Recovery floor for announcement fanouts whose workflow was lost between
    # commit and start; the claim on notified_at keeps a double run harmless.
    Sweep(
        command="fanout_announcements",
        workflow="announcement_fanout_sweep",
        cron="*/5 * * * *",
        run=lambda _now: build_announcement_fanout().fanout_due(),
        report="Notified {handled} subscriber(s) of announcements.",
    ),
    # Subscribers hear about a new programme within the hour, not the minute:
    # publishing is an editorial act, and a burst of mail on the exact tick
    # would catch the organizer's own last-second fixes.
    Sweep(
        command="announce_published_events",
        workflow="sphere_announcements_tick",
        cron="10 * * * *",
        run=lambda now: build_sphere_subscriptions().announce_published_events(now=now),
        report="Announced {handled} event(s) to subscribers.",
    ),
    # One cadence for every event, not a per-event knob: the export is a full
    # rewrite, so re-running is free and nothing accumulates between ticks. The
    # sweep is already bounded by sync-on and event-not-long-finished.
    Sweep(
        command="export_konwencik",
        workflow="konwencik_export_tick",
        cron="*/15 * * * *",
        run=lambda now: build_konwencik_export().run_sweep(now=now),
        report="Exported {handled} integration(s) to Konwencik.",
    ),
    # Rows only wait out the one-day invite window, so daily is enough.
    Sweep(
        command="purge_encounter_invitees",
        workflow="encounter_invitee_purge_tick",
        cron="40 3 * * *",
        run=_purge_stale_invitees,
        report="Purged {handled} stale encounter invitee(s).",
    ),
    # Listings stay open for days, so a day late to close one costs nothing.
    Sweep(
        command="close_stale_listings",
        workflow="listing_close_tick",
        cron="50 3 * * *",
        run=lambda now: build_listings().close_stale(now),
        report="Closed {handled} stale listing(s).",
    ),
)
