---
status: draft
updated: 2026-05-22
---

# Import proposals

## Running a pull

As an organiser, I want to trigger a pull from one or more configured
integrations, so that new form responses become sessions on my event
without me copying anything by hand.

As an organiser, I want to attach a recurring schedule to an import
integration, so that proposals arrive on their own without me triggering
each pull.

As an organiser, I want re-pulling the same source data to be a no-op,
so that I can pull as often as I like without creating duplicate
sessions.

As an organiser, I want to see a pull's progress as it runs, so that I
know whether it is stuck or making headway.

As an organiser, I want a pull that hits a fatal error to roll back
fully, so that a partial pull never leaves my event in an inconsistent
state.

## After a pull

As an organiser, I want a per-row report when a pull finishes, so that
I can see what landed, what was skipped, and what failed without
rummaging through the sessions list.

As an organiser, I want every row that failed to import to carry a short
reason I can group by, so that I can fix a class of problems in one
sweep instead of investigating row by row.

As an organiser, I want to export the pull report, so that I can share
it or reconcile it offline.
