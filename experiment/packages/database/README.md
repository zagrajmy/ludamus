# @zagrajmy/database

Effect `Layer`s that implement the ports in `@zagrajmy/core/ports` over
`effect/sql` against the SQLite file Django owns (PLAN.md D2). There is no
schema here: every query names Django's `db_table` and snake_case columns, and
every row is decoded with a Schema before it leaves the store.

```ts
import { DatabaseLive, DatabaseTest, StoresLive } from "@zagrajmy/database";
```

- `DatabaseLive`: all stores over `SqliteLive` (path from `AppConfig`).
- `StoresLive`: all stores, needing a `SqlClient`.
- `DatabaseTest`: all stores over a private snapshot of
  `../dev.e2e.sqlite3`, taken with SQLite's online backup from a read-only
  connection into a temp directory that is removed when the layer's scope
  closes. The seeded file is never opened for writing.
  `databaseSnapshotLayer(path)` does the same for another file.

## Shape of a store

Each `*-store.ts` exports `makeXStore` (an `Effect` that captures `SqlClient`,
so every method has `R = never`) and `XStoreLive = Layer.effect(XStore,
makeXStore)`. The service class lives in core, because core must not know
`effect/sql`; that is the one difference from rat-stack's `FileInspector`
shape.

Every method:

1. decodes its input with a Schema and fails with `InvalidStoreInput` before
   any statement runs;
2. runs parametrised tagged-template SQL (static column lists and sort columns
   come from constants through `sql.literal`, never from input);
3. decodes rows with Schema; any SQL or decode failure becomes
   `StoreError { operation, reason }`, where `reason` is the failure's tag
   only (no SQL, no values);
4. returns `NotFound` (or `Option.none`) when a scoped id does not belong to
   the scope it was asked under.

Writes that touch several tables run in `sql.withTransaction`. A capability
that needs several store calls to commit together wraps them in
`StoreTransaction.atomic` (nested store transactions become savepoints).
Write timestamps come from `DateTime.now` (Clock), so tests pin them with
`TestClock`. Reads that depend on time take an explicit `now`.

## Table → store map

| Django table(s) | Port (core) | Layer | Mirrors |
| --- | --- | --- | --- |
| `event`, `event_proposal_settings` | `EventStore` | `event-store.ts` | `chronology.EventRepository.list_for_events_page/list_by_sphere/read/read_in_sphere/read_by_slug`, `submissions.EventProposalSettingsRepository.read_by_event` |
| `session`, `session_facilitators`, `session_time_slots`, `session_tracks`, `session_field_value` | `SessionStore` | `session-store.ts` | `session_cards.scheduled_session_cards`, `SessionRepository.read_modal/read/read_by_event/create/update/soft_delete/restore/list_sessions_by_event/list_deleted_by_event/list_by_facilitator/slug_exists/set_*/read_*/save_field_values/count_by_track`, `sessions.review_inbox_proposals/own_pending_proposals` |
| `agenda_item` | `AgendaItemStore` | `agenda-item-store.ts` | `AgendaItemRepository.read_by_session/list_overlapping_in_space/create/delete` |
| `space` | `SpaceStore` | `space-store.ts` | `SpaceRepository.list_by_event/read`, `session_cards._location_index` |
| `time_slot` | `TimeSlotStore` | `time-slot-store.ts` | `TimeSlotRepository.list_by_event/read_by_event/pks_with_proposals` |
| `track`, `track_spaces`, `track_managers` | `TrackStore` | `track-store.ts` | `TrackRepository.*` (create/update/delete, lists, `_track_by_name`) |
| `facilitator` | `FacilitatorStore` | `facilitator-store.ts` | `FacilitatorRepository.*` |
| `proposal_category`, `session_field_requirement`, `time_slot_requirement` | `ProposalCategoryStore` | `proposal-category-store.ts` | `ProposalCategoryRepository.list_by_event/read/read_by_slug/get_category_stats/list_session_field_requirements/list_time_slot_requirements` |
| `session_field(+_option)`, `personal_data_field(+_option, +_value)` | `FieldStore` | `field-store.ts` | `SessionFieldRepository/PersonalDataFieldRepository.list_by_event/read_by_slug`, `PersonalDataFieldValueRepository.save/read_for_facilitator_event` |
| `session_participant` | `ParticipationStore` | `participation-store.ts` | `Session.enrolled_count/waiting_count/effective_participants_limit/seats_left/is_full`, `SessionManager.conflicted_user_ids`, `EnrollmentParticipationRepository`, `ParticipationPromotionRepository`, `AnonymousEnrollmentRepository`, `_check_and_create_enrollment` / `_handle_cancellation` writes |
| `party`, `party_membership` | `PartyStore` | `party-store.ts` | `party.PartyRepository.*` |
| `enrollment_config`, `user_enrollment_config`, `domain_enrollment_config` | `EnrollmentConfigStore` | `enrollment-config-store.ts` | `EnrollmentWindowRepository.list_for_event`, `EnrollmentConfigRepository.*`, `ParticipationPromotionRepository._config_allowances` |
| `user` | `UserDirectory` | `user-directory.ts` | `users.user_dto`, `companions.companions_of/sponsors_by_member` |
| `shadowban`, `event_ban` | `SafetyStore` | `safety-store.ts` | `ShadowbanRepository.banned_user_ids/banning_owner_ids/set_shadowban/list_session_shadowbanned`, `EventBanRepository.*` |
| `session_bookmark` | `BookmarkStore` | `bookmark-store.ts` | `bookmarks.BookmarkRepository.*` |
| `facilitator_change_log`, `schedule_change_log` | `ChangeLogStore` | `change-log-store.ts` | `FacilitatorChangeLogRepository.create/list_by_event`, `ScheduleChangeLogRepository.create/list_by_event/list_by_session` |
| `announcement` | `AnnouncementStore` | `announcement-store.ts` | published announcements of a sphere |
| `encounter`, `encounter_rsvp` | `EncounterStore` | `encounter-store.ts` | public encounters of a sphere |
| `django_session`, `user`, `sphere`+`django_site` | `DjangoSessionStore`, `UserStore`, `SphereStore` (database-local) | existing | auth bridge |
| feed, landing and shell reads | `FeedStore`, `LandingStore`, `ShellStore` | `feed-store.ts`, `landing-store.ts`, `shell-store.ts` | written by the page agent; composed in `apps/web/src/server/runtime.ts`, not in `StoresLive` |

## Semantics a page or capability needs to know

**Status sets.** `OCCUPYING_PARTICIPATION_STATUSES = confirmed, offered`:
both hold a seat. `enrolledCount` counts them, `waitingCount` counts
`waiting`. The shadowban warnings and "currently in" checks use all three.

**Seats** (`SessionSeats`, on every `SessionCard` and from
`ParticipationStore.seats`), computed in SQL from `now`:

- a window is *active* when `start_time < now < end_time`;
- it is *eligible* for a session when active, `participants_limit <> 0`, and
  either `limit_to_end_time = 0` or the agenda item starts before the window
  ends (an unscheduled session never passes the second test);
- `effectiveParticipantsLimit` is `0` for a limit of 0, the limit itself when
  no window is eligible, otherwise `ceil(limit * max(percentage) / 100)`;
- `seatsLeft = max(0, effective - enrolled)`;
- `isFull = limit <> 0 and enrolled >= effective`;
- `eligibleWindowIds` are the eligible window ids; intersect them with the
  viewer's open windows to answer "may this viewer enroll".

**Public schedule.** A session is on the event page when it is alive, has an
agenda item, and is in no track with `is_public = 0`
(`session_visibility.public_scheduled_sessions`). The feed's `sessionCount`,
the cards and the modal read all use that one predicate.

**Feed visibility.** Listed means `publication_time IS NOT NULL AND
publication_time <= now AND visibility = 'public'`
(`event_visibility.listed_events`). `includeHidden` drops the filter (managers).
An event page is open when published or `unlisted` (`isOpen` in core).

**Soft delete** (`session`, `facilitator`). Reads go through the alive rows
(`deleted_at IS NULL`); the bins (`listDeletedByEvent`) and identity checks
reach deleted rows: `FacilitatorStore.slugExists` and
`readBySlugIncludingDeleted` include dead facilitators (their slug stays
reserved), `SessionStore.slugExists` is alive-only as in Django.
`softDelete` on a dead row and `restore` on a live row are `NotFound`.
Soft delete stamps `deleted_at` only, never `modification_time`.

**Event scoping.** Every write and every by-id read that a request can name
takes the event and filters on it in SQL, so a foreign id is `NotFound` with
no side effect. Where Django scopes through `category__event_id`
(`readInEvent`, `restore`, `listByEvent`, `listDeletedByEvent`,
`countByTrack`), so does the store: a session without a category is invisible
there, exactly as in the panel today. `create` and `set*` refuse
facilitators, time slots and tracks of another event (and dead facilitators).

**Timestamps and defaults.** Inserts write the columns Django's model
defaults fill (`creation_time`/`modification_time` = now, empty strings for
`ident`, `cover_image`, `claim_token`, `internal_comment`, `deleted_at`
NULL). `SessionStore.update` mirrors `QuerySet.update`: it does not touch
`modification_time`. Participation status writes do (as `save()` and the
promotion repository's `update(..., modification_time=now)`). Datetimes are
written as `YYYY-MM-DD HH:MM:SS[.ffffff]` UTC, millisecond precision.

**JSON columns** (`session_field_value.value`, `personal_data_field_value.value`,
`proposal_category.durations`, change-log `changes`) are written in Python's
`json.dumps` format (`", "` and `": "` separators, non-ASCII as `\uXXXX`),
so Django's exact-match field filters and the panel search (which matches
both the raw term and its JSON-escaped form) find rows written by either app.

**Change logs.** Facilitator edits log `[{"field", "field_id", "old", "new"}]`
(core names it `fieldId`); schedule changes log action, old/new space and
times. The capability writes the log next to the change inside one
`StoreTransaction.atomic`, as the Django services do.

**Slugs.** Generation is a rule, not SQL, so it is not here: the capability
slugifies and probes `slugExists` (sessions and facilitators use
`mills.submissions.mapping.generate_unique_slug`: unidecode slug, up to 8
tries with a `-{token_urlsafe(3)}` suffix, then fail; tracks, categories and
fields use Django's `slugify` and `repositories/slugs.generate_unique_slug`: 4
tries, then keep the last candidate). `TrackStore.create/update` take the
slug they are given. Proposals are created with status `pending` (Django has
no `proposal` status).

**Concurrency.** SQLite has no `SELECT ... FOR UPDATE`; the client opens
write transactions with `BEGIN IMMEDIATE`, which serialises writers the way
Django's row locks do for this workload.

## Read bounds

Every list has an explicit `LIMIT` from `ROW_BUDGET` in `sql-fragments.ts`
(guesses, not measurements; the largest seeded event has 112 scheduled
sessions and 72 facilitators):

| Read | Key / order | Budget |
| --- | --- | --- |
| feed events | `sphere_id`, `start_time, id` | 500 |
| sphere events | `sphere_id`, `start_time DESC` | 1000 |
| scheduled cards | `event_id`, `agenda.start_time, id` | 5000 sessions; children by `IN (scope subquery)`, 7 statements per page whatever the size |
| proposal cards | `event_id`, `creation_time DESC` | 1000 |
| panel sessions / facilitators | `event_id`, user sort then `id` | 5000 (facilitator pickers pass a smaller `limit`) |
| participations of a session | `session_id`, `creation_time, id` | 2000 |
| spaces, slots, tracks, categories, fields | `event_id`, model ordering | 2000 / 1000 / 500 / 500 / 500 |
| change logs | `event_id` or `session_id`, `creation_time DESC, id DESC` | keyset pages of 200 (`before` cursor) |
| bans, parties, announcements, encounters | owner key | 2000 / 200 / 50 / 200 |

## Not ported

- Avatar URLs: Django resolves Gravatar (`display_avatar_url`); stores return
  `avatarUrl` and `useGravatar` raw.
- File URLs: `coverImage`, `logo`, `headerImage` are storage paths; prefix
  them with the media URL.
- A room filed under another event (`session_cards._location` fallback):
  such a card gets `NO_LOCATION`.
- Time-slot, space, category and field CRUD, schedule-change acknowledgement,
  errata, imports and the confirmation dashboards are outside the slice.
