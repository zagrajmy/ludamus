# Plan 018: Fix skip-notice level and cancel-without-config

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to
> the next step. If anything in the "STOP conditions" section occurs,
> stop and report — do not improvise. Your reviewer maintains
> `plans/README.md`; do not edit it.
>
> **Drift check (run first)**:
>
> ```sh
> git diff --stat 3a06ef4..HEAD -- \
>   src/ludamus/adapters/web/django/views.py \
>   tests/integration/web/chronology/test_session_enroll_page.py
> ```
>
> If either file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on
> a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: MED (user-facing behavior in the enrollment flow)
- **Depends on**: 017 (merged into this branch)
- **Category**: bug
- **Planned at**: commit `3a06ef4`, 2026-07-11

## Why this matters

Plan 017's behavior audit recorded two suspected bugs, both confirmed
against live code. (1) Skip notices ("Skipped (already enrolled or
conflicts): …") flash at `messages.SUCCESS`, so a user whose entire
request was skipped sees a green success toast for an action that did
not happen. (2) When an organizer deletes every `EnrollmentConfig` row
for an event, users with existing enrollments cannot cancel them —
the cancel-only carve-out still requires at least one config row to
exist, so enrollees are stuck holding seats they want to release.

## Current state

- `src/ludamus/adapters/web/django/views.py:1684-1709` —
  `_send_message` sends one message per outcome bucket, ALL via
  `messages.success`, including the skipped bucket:

  ```python
  (
      enrollments.skipped_users,
      _("Skipped (already enrolled or conflicts): {}"),
  ),
  ```

  followed by `messages.success(self.request, message.format(...))`
  for every non-empty bucket.

- `src/ludamus/adapters/web/django/views.py:1069-1095` —
  `_validate_request`. Cancel-only requests already have a carve-out
  that accepts ANY config row (even inactive):

  ```python
  if enrollment_requests and all(
      req.choice == EnrollmentChoice.CANCEL for req in enrollment_requests
  ):
      if not (config := event.enrollment_configs.order_by("pk").first()):
          raise RedirectError(
              reverse("web:chronology:event", kwargs={"slug": event.slug}),
              error=_(
                  "No enrollment configuration is available for this session."
              ),
          )
      return config
  ```

  The zero-rows case raises — that is the bug. The returned config is
  passed to `_process_enrollments(enrollment_config=...)` at
  `views.py:1286-1290` and threads to `views.py:1475` and `:1498`.
  Investigate what the config is actually used for on a
  pure-cancellation pass before choosing the fix shape (see Step 2).

- Tests pinning the CURRENT buggy behavior (both must be updated to
  pin the FIXED behavior, not deleted):
  - `tests/integration/web/chronology/test_session_enroll_page.py` —
    `test_post_shadowbanned_connected_user_skipped_neutrally` asserts
    `(messages.SUCCESS, "Skipped …")`; `test_post_session_host_skipped`
    and `test_post_time_conflict_skipped` likewise assert SUCCESS for
    skip notices; `test_post_cancel_when_no_enrollment_config` asserts
    the error redirect.
- Message levels available: `messages.warning` renders as the amber
  alert in the tessera toast styling (see how existing warnings render
  in `templates/` — grep `alert-warning` / message level tags).
- No message STRINGS change in this plan — only levels and control
  flow — so the PL catalog (`mise run messages-check`) must stay
  green with no catalog edits.
- Environment notes: run `mise trust`, `MISE_ENV=sandbox mise install`,
  `poetry install` first; prefix test/check runs with
  `PATH="$(pwd)/.venv/bin:$PATH"`; the CI-style gate is
  `mise run check` (there is no `prcheck` task).

## Commands you will need

| Purpose | Command | Expected on success |
| --- | --- | --- |
| Install | `mise install && poetry install` | exit 0 |
| All Py tests | `mise run test:py` | all pass |
| Translations | `mise run messages-check` | fresh, all translated |
| CI-style gate | `mise run check` | exit 0 |

## Scope

**In scope** (the only files you should modify):

- `src/ludamus/adapters/web/django/views.py`
- `tests/integration/web/chronology/test_session_enroll_page.py`
- `tests/integration/web/chronology/test_session_enroll_consent.py`
  (revision 1: `test_race_on_a_member_who_enrolled_themselves_skips`
  pins the same SUCCESS-level skip message — update it to WARNING)

**Out of scope** (do NOT touch, even though they look related):

- `src/ludamus/locale/pl/LC_MESSAGES/django.po` — no string changes,
  so no catalog changes; if `messages-check` demands one, STOP.
- The skip-collection logic itself (which users get skipped and why).
- `gates/web/django/chronology/anonymous.py` — the anonymous flow has
  its own messaging; audit it for the same level bug and REPORT in
  your notes, but do not change it here.
- Templates and tessera components.

## Git workflow

- Commit style example:
  `fix(enroll): warn on skips, allow cancel with no config`.
- End the commit message with
  `Co-authored-by: hasparus <hasparus@gmail.com>`.
- Do NOT push or open a PR.

## Steps

### Step 1: Skip notices become warnings

In `_send_message`, send the skipped bucket via `messages.warning`
and keep every other bucket on `messages.success`. The clean shape is
to add the level to each tuple instead of branching inside the loop:

```python
for users, message, level in (
    (..., _("Enrolled: {}"), messages.SUCCESS),
    ...
    (
        enrollments.skipped_users,
        _("Skipped (already enrolled or conflicts): {}"),
        messages.WARNING,
    ),
):
    if users:
        messages.add_message(
            self.request, level, message.format(", ".join(users))
        )
```

Update the three skip-asserting tests to expect
`(messages.WARNING, "Skipped …")` (import the constant the way the
file already does).

**Verify**:
`mise run test:py` → all pass after the test updates.

### Step 2: Cancel works with zero EnrollmentConfig rows

First read `_process_enrollments` (`views.py:1286` onward) and every
use of its `enrollment_config` parameter (`:1475`, `:1498`) and
determine what a pure-cancellation pass actually reads from the
config. Expected finding: cancels release seats and never consult
slot math. Then, in the cancel-only branch of `_validate_request`,
replace the raise with a pass-through:

- Change `_validate_request` to return `EnrollmentConfig | None`,
  returning `None` when the event has no config rows AND the request
  is cancel-only (keep the raise for the mixed/enroll path).
- Type the `enrollment_config` parameter as
  `EnrollmentConfig | None` down the call chain ONLY along the paths
  a cancel-only request can reach; guard any config attribute access
  that a cancel-only pass could hit. mypy strict will enumerate the
  exact spots — fix each by guarding, not by asserting.
- Revision 1, confirmed edge case: a batch that is cancel-only by
  `_validate_request`'s definition can still carry a positive
  `guest_seats_needed`, which reaches
  `enrollment_config.get_available_slots(...)` in
  `_is_capacity_invalid`. Add an explicit behavior guard there: when
  `enrollment_config is None`, treat available slots as 0 (any guest
  increase is rejected as over capacity) — a real branch, not a
  checker-appeasing assert. Add a test: zero configs + a POST that
  cancels while raising the guest count → guests rejected per the
  existing over-capacity semantics.

Rewrite `test_post_cancel_when_no_enrollment_config` to pin the FIXED
behavior: arrange an existing CONFIRMED participation, delete all
configs, POST a cancel; assert the "Cancelled: …" message, the
participation row gone, and the redirect to the event page. Keep a
variant asserting that an ENROLL attempt with zero configs still gets
the "No enrollment configuration…" error (that path must not change).

**Verify**:
`mise run test:py` → all pass, including the rewritten test and the
still-guarded enroll-path test.

### Step 3: Full gate

**Verify**: `mise run check` → exit 0; `mise run messages-check` →
"Translations fresh"; `mise run test:py` → all pass.

## Test plan

- Skip-level: the three updated assertions pin WARNING for skips and
  SUCCESS for the other buckets (one existing mixed-outcome test,
  e.g. cancel-and-enroll, must still assert its SUCCESS messages —
  do not weaken it).
- Cancel-without-config: happy path (cancel succeeds, row deleted,
  message shown) + guard path (enroll still rejected).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -c "messages.warning\|messages.WARNING"
  src/ludamus/adapters/web/django/views.py` returns ≥ 1
- [ ] `mise run test:py` exits 0, including the rewritten
  `test_post_cancel_when_no_enrollment_config`
- [ ] `mise run messages-check` passes with NO changes to the PL
  catalog (`git status` shows no .po file)
- [ ] `mise run check` exits 0
- [ ] No files outside the in-scope list are modified (`git status`)

## STOP conditions

Stop and report back (do not improvise) if:

- The excerpts no longer match the live code (drift).
- Step 2's investigation shows a cancel-only pass genuinely reads the
  config (slot math, capacity, promotion) — the None-return shape
  would then change behavior; report what it reads instead of
  guessing.
- Guarding the `EnrollmentConfig | None` type ripples into files
  outside the in-scope list.
- `messages-check` demands catalog changes (means a string changed —
  it must not).

## Maintenance notes

- The anonymous enrollment flow (`gates/.../chronology/anonymous.py`)
  may carry the same SUCCESS-level skip bug — the executor reports
  findings; fixing it is a follow-up.
- When the enrollment view migrates to gates (refactor #1), these
  two behaviors are pinned by tests and must survive the move.
- Reviewers should scrutinize: no skip message string changed (PL
  catalog untouched), and the enroll-with-zero-configs rejection
  still stands.
