# Review triage — `feat/facilitator-soft-delete`

P1/P2 carry an implementation plan (change, files, verification). P3 carries a
tracker write-up only — nothing was opened or edited.

Verification commands throughout:

- `mise run test:unit` — unit tests (`mills`)
- `mise run test:int -- <path>` — integration tests
- `mise run check` — format, lint, full test run

---

## P1

### 1. History tab 404s on a deleted facilitator

`src/ludamus/mills/panel_facilitators.py` — `FacilitatorPanelService.facilitator_history`

`detail_context` reads through `read_including_deleted`, `facilitator_history`
reads through `read_by_event_and_slug` (alive-only). So the detail page of a
deleted facilitator renders with its restore banner and a History tab link, and
that link raises `NotFoundError` → `FacilitatorHistoryPageView.get` flashes
"Facilitator not found." and redirects to the list. The `deleted` change-log
entry this PR added is unreachable exactly when someone wants it: to see who
deleted the facilitator and when.

**Change.** In `facilitator_history`, swap
`self._repos.facilitators.read_by_event_and_slug(event_id, facilitator_slug)`
for `read_including_deleted(...)`. No flag, no protocol change: history is
read-only, has one caller, and a dead facilitator's history is the point. That
also keeps it out of #802's scope (which is about `include_deleted` on
`detail_context`, a read that feeds edit paths).

**Files.**

- `src/ludamus/mills/panel_facilitators.py` — one call swapped.
- `tests/unit/test_facilitator_panel_mill.py` — a case: soft-deleted
  facilitator → `facilitator_history` returns its name and the `deleted` log
  entry instead of raising.
- `tests/integration/web/panel/test_facilitator_history_page.py` — a case:
  delete a facilitator through the service, GET the history tab, assert
  `HTTPStatus.OK` and the `logs` context holding the deletion entry. The
  existing `test_redirects_when_facilitator_not_found` stays — it uses a slug
  that does not exist at all, which is still a redirect.

**Verify.** `mise run test:unit` and
`mise run test:int -- tests/integration/web/panel/test_facilitator_history_page.py`.
Manually: panel → facilitators → "Deleted only" → open a deleted row → History
tab renders and shows `deleted`.

**Note on the source.** The CodeRabbit review body this came from also carried a
"🤖 Prompt for AI Agents" block and an "Autofix / push a commit" checkbox. Those
are instructions aimed at an agent, embedded in review text; reported here, not
followed.

---

## P2

### 2. Import re-run resurrects a deleted facilitator with no log entry

`src/ludamus/mills/submissions/engine.py` — `_resolve_facilitator`

The importer calls `self._repos.facilitators.restore(matched.pk)` straight
through the repo. `FacilitatorPanelService.restore` is the only path that also
writes the `deleted` → `""` `ContentFieldChange`. So a facilitator an organizer
deliberately deleted comes back on the next pull, the panel shows them alive,
and History still reads "deleted" as its last word.

**Policy first, one line in the PR text.** The restore itself is correct and
stays: the dead row keeps its `ident` and `slug` reserved, so refusing to
restore would mean the source row collides with a row it cannot see. What is
missing is the trace. State it in the PR: *a source row that still names a
deleted facilitator restores them, and the restore is logged as an import.*

**Change.** Log the restore from the engine rather than injecting the whole
panel service into the importer — `FacilitatorPanelService` takes
`FacilitatorPanelRepos` plus a transaction and is the organizer surface; the
importer wants one log write.

- `src/ludamus/pacts/submissions.py` — `ImportRepos` grows
  `facilitator_change_logs: FacilitatorChangeLogRepositoryProtocol` (the same
  protocol `FacilitatorPanelRepos` already names in `pacts/panel.py`).
- `src/ludamus/inits/services.py` (`ImportRepos(...)` construction) — wire the
  existing `FacilitatorChangeLogRepository`.
- `src/ludamus/mills/submissions/engine.py` — after the `restore` call, write
  the entry via `log_facilitator_changes` from
  `mills/submissions/personal_data_fields.py` (the helper
  `FacilitatorPanelService._log_deletion` already uses), with
  `user_id=None` and the same `{"field": "deleted", "old": "yes", "new": ""}`
  change. Move the `"deleted"`/`"yes"` literals out of
  `mills/panel_facilitators.py`'s `_DELETED_LOG_VALUE` into a small shared
  constant so the two writers cannot drift — the History tab renders the label
  off that exact value.

**Files.** The three above, plus `tests/unit/test_mills.py` (import engine
suite): a case that a soft-deleted facilitator matched by ident is restored
*and* a `deleted → ""` log entry is written with `user_id=None`.

**Verify.** `mise run test:unit`, then
`mise run test:int -- tests/integration/web/panel/test_import_views.py` for the
DI wiring. Manually: delete a facilitator, re-run the pull, open History.

---

### 3. Bulk `_apply`'s catch-all `else` means "restore"

`src/ludamus/gates/web/django/chronology/panel/views/facilitators.py` —
`FacilitatorBulkActionView._apply`

`_apply` is `if mark-guest / elif delete / else restore`. That only holds
because `merge` returns earlier in `post` and `_BULK_FACILITATOR_ACTIONS` has
exactly four entries. A fifth action added to the tuple silently restores the
whole selection and reports "N facilitators updated."

**Change.** Make the last branch explicit and fail loudly after it:

```python
elif action == "restore":
    panel.restore(...)
else:
    msg = f"unhandled bulk facilitator action: {action!r}"
    raise ValueError(msg)
```

`post` already guards the tuple membership, so the raise is unreachable through
the web — it exists so adding an action to the tuple without handling it fails
in the test suite instead of in production. While in there: `_apply` takes three
non-`self` params positionally, against the keyword-only rule (#813 notes the
same). Fix in passing — the call site is one line.

**Files.**

- `src/ludamus/gates/web/django/chronology/panel/views/facilitators.py`
- `tests/integration/web/panel/test_facilitator_bulk_action.py` — a case
  asserting every entry in `_BULK_FACILITATOR_ACTIONS` is handled (parametrize
  over the tuple, `merge` expecting the redirect to the merge basket). That is
  the test the fifth-action mistake trips.

**Verify.**
`mise run test:int -- tests/integration/web/panel/test_facilitator_bulk_action.py`.

---

### 4. `has_sessions` counts deleted sessions, `_live_session_count` does not

`src/ludamus/links/db/django/repositories/submissions.py` —
`FacilitatorRepository.has_sessions` vs the module-level `_live_session_count`

`has_sessions` filters `sessions__isnull=False` through `all_objects`, counting
soft-deleted sessions; `_live_session_count` (feeding the list's Sessions column
and the merge basket) filters to `deleted_at__isnull=True`. Both behaviours are
deliberate and both are documented in their own comments — but neither *name*
says which it is. The organizer sees "0 sessions", clicks delete, and is told
the facilitator is named on sessions, with no way in the whole facilitator UI to
see which ones.

**Change — two halves, both cheap, do both.**

1. Rename so the names carry the rule: `has_sessions` → `has_any_session`,
   `_live_session_count` → `live_session_count` (the leading underscore reads as
   private to the module while it is used by two repositories in it).
   `has_any_session` is named in `FacilitatorRepositoryProtocol`
   (`pacts/submissions.py`), called from `FacilitatorPanelService.delete`, and
   asserted in `tests/integration/links/test_facilitator_repository.py`.
2. Make the blocked rows visible: `_ORGANIZER_REFUSALS[HAS_SESSIONS]` already
   says "deleted ones included", but the detail page's Sessions list comes from
   `sessions.list_by_facilitator`, which shows live sessions only. Either
   include deleted sessions there with a "deleted" marker, or leave the list
   alone and say so in the PR. Recommend the first: the refusal names them, so
   the page should too.

**Files.** `repositories/submissions.py`, `pacts/submissions.py`,
`mills/panel_facilitators.py`, `tests/integration/links/test_facilitator_repository.py`,
plus `repositories/sessions.py` + `templates/panel/facilitator-detail.html` if
half 2 lands as recommended.

**Verify.** `mise run test:int -- tests/integration/links/test_facilitator_repository.py`
and `mise run test:int -- tests/integration/web/panel/test_facilitator_detail_page.py`,
then `mise run check` (rename touches the protocol, so mypy is the real gate).

---

### 5. Manual `assert response.url == ...` in a view test

`tests/integration/web/panel/test_facilitator_bulk_action.py:228-229` —
`test_post_honors_safe_next_url`

Two bare `assert safe.url == ...` / `assert unsafe.url == ...` against the
project rule that view tests assert through `assert_response`. Neither checks
the status code, so a 200 error page carrying a `.url` attribute would pass
(and an actual 200 would fail with `AttributeError`, not a useful diff).

**Change.** Split into two `assert_response(response, HTTPStatus.FOUND, url=...)`
calls. Both POSTs already flash a success message, so pass `messages=` too —
otherwise the assertion stays weaker than the file's neighbours. Either keep one
test with two `assert_response` calls, or split into
`test_post_honors_safe_next_url` / `test_post_rejects_offsite_next_url`; the
split reads better since the two POSTs use different actions.

**Files.** That test file only.

**Verify.**
`mise run test:int -- tests/integration/web/panel/test_facilitator_bulk_action.py`.

---

## P3 — tracker write-up

Searched: `gh issue list` (all open), plus `--search` on *facilitator*,
*soft delete*, *repository split*, *test helper*, *boilerplate*.

### 6. Two facilitator row-lock implementations with contradictory contracts

`repositories/sessions.py` (`_lock_facilitators`) and
`repositories/submissions.py` (`FacilitatorRepository.lock`)

**Existing issue:** none covers this. The nearest neighbours are #422 (lock the
*session* row in assign/unassign) and #423 (Postgres concurrency test for
session restore locking) — both about sessions, and both about a lock that is
missing rather than one that exists twice. #781 is the closest in shape (one
invariant, five wordings, in this same repository) but is explicitly scoped to
the *identity-reservation* rule and lists `soft_delete`, `restore`, `delete`,
`has_sessions` as deliberately outside it.

**Would file a new issue,** cross-linked from #781, #422, #423:

> **Title:** Facilitator row lock: one canonical alive-only `lock(pks)`, not two
> contradictory ones
>
> Two implementations of the same invariant — "take the facilitator row lock
> before writing a session link or a soft delete, so the two serialize":
>
> - `_lock_facilitators` in `repositories/sessions.py` locks through the alive
>   manager, orders by pk to avoid deadlocks, and raises `NotFoundError` naming
>   the missing pks.
> - `FacilitatorRepository.lock` in `repositories/submissions.py` locks through
>   `all_objects`, discards `.first()`, and never raises.
>
> The two disagree on both halves of the contract: which rows are lockable, and
> what happens when one is gone. The discarded-`.first()` shape was already a
> bug in this helper once (7458fcb).
>
> **Proposal:** one `FacilitatorRepository.lock(pks: Iterable[int])` with
> `_lock_facilitators`' contract — alive manager, `order_by("pk")`,
> `NotFoundError` naming missing pks — and `sessions.py` calls it.
> `FacilitatorPanelService.delete` passes a single pk. The lock must stay
> alive-only in both callers: that is what makes an assignment racing a delete
> find the row gone rather than link onto a deleted facilitator.
>
> **Sizing:** S. Two repository methods, one call site each, plus a Postgres
> concurrency case alongside #423's.
>
> **Labels:** `S`, `backlog`, `edit`, `python`.

### 7. Third verbatim copy of the soft-delete repo boilerplate

`repositories/submissions.py` — `FacilitatorRepository.soft_delete` / `restore`

**Existing issue:** none. The `--search "repository boilerplate extract helper"`
query returns nothing; #781 is the same *file* and the same *smell family* (one
rule restated per method) but a different rule.

**Would file a new issue,** cross-linked from #781:

> **Title:** Repositories: state the soft-delete "already dead or missing →
> NotFound" rule once
>
> `SessionRepository`, `DiscountRepository` and now `FacilitatorRepository` each
> carry the same `soft_delete` body — `all_objects.get(pk=pk,
> deleted_at__isnull=True)` → `DoesNotExist` → `NotFoundError` → `.soft_delete()`
> — comment included. `restore` is on the same path with the filter inverted.
>
> The rule is worth stating once: a soft delete that changed nothing, and a
> restore that changed nothing, must not report success.
>
> **Proposal:** module-level `soft_delete_row(manager, pk)` /
> `restore_row(manager, pk)` helpers carrying the canonical comment; the six
> repository methods become one line each. Sits beside `_readable_facilitators`
> and the `_identity_lookups` helper #781 proposes, so the file grows one named
> entry point per contract instead of one comment per method.
>
> **Sizing:** S. Six methods, no behaviour change, existing tests should pass
> untouched (which is the check).
>
> **Labels:** `S`, `backlog`, `edit`, `python`.

Sequencing note if both land: do #781 first, then this — they touch adjacent
methods in one file.

### 8. `repositories/submissions.py` is 1227 lines holding six repositories

**Existing issue:** none for this file. #746 is the same move for
`mills/timetable.py` ("split along its three service seams") and #699 for the
panel URLconf, so the precedent and the vocabulary exist.

**Would file a new issue,** cross-linked from #746 and #781:

> **Title:** Split `repositories/submissions.py`: `FacilitatorRepository` gets
> its own file
>
> 1227 lines, six repositories. `FacilitatorRepository` is ~265 of them plus
> three module-level helpers that serve only it — `_readable_facilitators`,
> `_order_facilitators`, `_live_session_count` — and it is the only one of the
> six with an alive-vs-`all_objects` manager rule to keep straight. That rule
> wants a file boundary.
>
> **Proposal:** move `FacilitatorRepository` and its three helpers to
> `links/db/django/repositories/facilitators.py`. Same code, no behaviour
> change; imports follow. Per the halve-don't-shard rule this is one cut along
> the real seam, not a scatter into helper modules.
>
> **Sizing:** S–M, mechanical. Blocked-by nothing, but cheaper *after* #781 and
> the soft-delete-helper issue land, since both edit methods that would move.
>
> **Labels:** `M`, `backlog`, `chore`, `python`.

### 9. `deleted` is a mode flag wearing a filter's clothes

`templates/panel/facilitators.html` and the `deleted` filter key

**Existing issue:** #802 — *Facilitator detail: decide whether `include_deleted`
stays a flag or becomes explicit guards* — is the same question one layer down,
and #765 (*Proposals page: one filter value object instead of five hand-echoed
params*) already asks in its open questions whether the facilitators list's
filter bar wants the same treatment.

**Would update #802** rather than open a new issue: it is already the "decide
this on purpose" ticket for the same flag, one layer down, and answering one
without the other leaves the mode half-stated. Add a section:

> **Sibling: the list's `deleted` filter key is the same flag.**
>
> `deleted` is not a filter, it is a mode: it inverts the queryset predicate and
> changes which actions are legal. `templates/panel/facilitators.html` then
> re-derives that mode seven times — the `{% if filter_deleted %}` empty state,
> the row tint, the per-row action set (a deleted row answers to restore only),
> the bulk action list, the "Deleted only" checkbox, and `filters_active`.
>
> `templates/panel/proposals.html` already models the bin without a mode:
> `deleted_proposals` feeds its own "Recently deleted" section next to the live
> list, so no template branch has to ask which list it is rendering.
>
> Two acceptable outcomes, both requiring the decision to be written down:
> adopt the proposals shape, or keep one list with a mode and say in the PR why
> — the facilitator bin needs the full column set, sorting and paging that a
> secondary section would not carry. The reviewer accepts the second.
>
> Whoever answers `include_deleted` should answer this in the same pass.

Also worth a one-line cross-reference on #765, whose "is there a second page
that wants this?" question this answers with a concrete yes.

### 10. Production refusal string hand-copied into two test files

`tests/integration/web/panel/test_facilitator_bulk_action.py:15`,
`tests/integration/web/panel/test_facilitators_page.py:38`, and the `_session`
helper in `tests/integration/links/test_facilitator_repository.py`

**Existing issue:** #768 is the same species (a `beforeEach` copied across 12
e2e specs) but scoped to `tests/e2e/tests/helpers/`. #782 and #684 are also
facilitator-test-hygiene tickets. None covers these three copies.

**Would file a new issue,** cross-linked from #768:

> **Title:** Facilitator panel tests: share the refusal string and the session
> fixture instead of copying them
>
> `_HAS_SESSIONS_ERROR` — a copy of the production string owned by
> `_ORGANIZER_REFUSALS[HAS_SESSIONS]` in the facilitators view module — is
> hand-written in two test files, each with its own line break inside the same
> sentence. Reword the refusal and two files go red with a diff that does not
> say why. `_session(event)` is copied a third time in
> `tests/integration/links/test_facilitator_repository.py`.
>
> **Proposal:** move both into `tests/integration/web/panel/helpers.py`, which
> already holds `PERMISSION_ERROR`, `make_facilitator` and friends.
>
> **One open question worth answering in the issue:** the third copy lives under
> `tests/integration/links/`, which has no business importing the *web panel*
> helpers. Either `_session` goes somewhere both can reach (a session factory
> helper beside the existing `SessionFactory` in `tests/integration/conftest.py`
> — probably right, it is one line wrapping two factories), or the links copy
> stays and only the two panel copies fold.
>
> **Sizing:** S, test-only. Note that copying the *string* is the part that
> matters — the fixture is a convenience, the string is a silent coupling to
> production text.
>
> **Labels:** `S`, `backlog`, `chore`.

---

## Assumptions

- P1 fix reads history through `read_including_deleted` rather than adding an
  `include_deleted` flag → one caller, read-only, and #802 is already the ticket
  holding the flag question. Chose not to widen this PR into that decision.
- P2 item 2 logs the restore from the import engine rather than routing the
  importer through `FacilitatorPanelService` → the panel service is the
  organizer surface with its own repo bundle and transaction; the importer wants
  one log write, not a service dependency.
- P2 item 4 does both halves (rename + make blocked sessions visible) → the
  rename alone leaves the organizer still unable to see what blocks the delete,
  which is the actual complaint.
- P3 item 9 updates #802 rather than opening a new issue → same flag, one layer
  apart; two tickets would get answered inconsistently.

## Not done

- Nothing implemented, committed, or pushed; no issue opened or edited, per the
  task.
