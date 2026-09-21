# Fix what the session status display gets wrong

Five defects in how a session's state is written, counted and shown. All
five are live today, none needs a schema change, and none waits on the
speculative [session buckets](session-buckets.md) redesign. One release.

They add no user stories: every fix restores what the page it touches
already promises.

## The defects

### 1. Accepting a proposal confirms the schedule behind the organizer's back

`ProposalAcceptanceService.accept_session` (`mills/chronology.py`) creates
the `AgendaItem` with `session_confirmed=True` hard-coded, so the public
accept flow records the facilitator's agreement to a slot nobody asked them
about. The two other writers (`TimetableService.assign_session`,
`revert_change`) read `Event.auto_confirm_sessions`.

Fix: read `auto_confirm_sessions` for the event and pass it. One line plus
the event read.

### 2. `accepted_count` counts everything that is not pending

`SubmissionRepository.get_category_stats`
(`links/db/django/repositories/submissions.py`) annotates
`accepted_count` as `Count("sessions", filter=~Q(sessions__status=PENDING))`,
so on-hold and rejected proposals inflate the figure the CFP page prints as
accepted.

Fix: `filter=Q(sessions__status=SessionStatus.ACCEPTED)`.

### 3. Two badge maps disagree about the same status

`panel/_proposal_status_badge.html` renders `on_hold` info-blue;
`panel/parts/confirmation-status-badge.html` renders it neutral-grey. The
second exists only for the confirmation facilitator card's status groups.

Fix: delete `confirmation-status-badge.html` and include the proposal badge
from `confirmation-facilitator-card.html`.

### 4. The same session badges differently on three pages

`_proposal_status_badge.html` derives a fifth status — `accepted AND
is_scheduled` renders as "Scheduled" — from a slot its callers fill
inconsistently: `_proposal_cell.html` passes `proposal.is_scheduled`,
`proposal-actions.html` passes `agenda_item`, `proposals.html` passes the
literal `False`, and `facilitator-detail.html` passes nothing.

Fix: the badge takes the session (or proposal) object and reads placement
off it, so no caller can pass a different answer. Three include sites lose
their `is_scheduled=` argument.

### 5. A placement filter sits in the status select

`SCHEDULED_FILTER` (`pacts/panel.py`) is offered in the proposals page's
status dropdown next to the four real statuses, and
`ProposalPanelService.list_context` (`mills/panel_proposals.py`) makes
picking a real status *exclude* placed sessions so the backlog looks right.
A filter narrowing one axis is answering two — the type error CLAUDE.md
warns about, and the reason a placed pending session is invisible under
"Pending".

Fix: two controls. The status select lists statuses only and stops implying
anything about placement; a new "On the timetable" select offers
`all` / `planned` / `unplanned`. `ProposalListQuery` gains `scheduled`;
`SCHEDULED_FILTER` and the exclusion rule go. The default proposals view
stays what it is today — pending, not on the timetable — by sending both
params.

## Testing

- `mills`: `accept_session` honours `auto_confirm_sessions` both ways;
  `list_context` maps the status and planned params onto the repository
  filters, including status-plus-planned together.
- `links`: `get_category_stats` with one session per status.
- `gates`: the proposals page's filter options and the selected values in
  `context_data`.
- `tests/e2e`: one proposal shows the same badge on the list, its detail
  page and the facilitator page.
