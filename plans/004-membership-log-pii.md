# Plan 004: Stop logging user e-mail addresses in the membership client

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to
> the next step. If anything in the "STOP conditions" section occurs,
> stop and report — do not improvise. When done, update the status row
> for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 0bec0f2..HEAD -- src/ludamus/links/ticket_api.py tests/integration/links/test_ticket_api.py`
> If those files changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on
> a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `0bec0f2`, 2026-07-09

## Why this matters

The membership API client logs the user's e-mail address at INFO on
every successful lookup and in both exception paths. Production logging
runs at INFO, so routine PII (e-mail tied to membership/paid-slot
status) accumulates in application logs and any log aggregation,
widening the exposure surface and complicating retention/GDPR posture
for a Polish user base. The file itself already documents the intent to
keep e-mails out of logs in its not-configured branch — the other three
log calls just never got the same treatment.

## Current state

- `src/ludamus/links/ticket_api.py:23-52` — `fetch_membership_count`;
  the three offending log calls:

  ```python
  logger.info(
      "Fetched membership count %d for user %s", membership_count, email
  )
  ```

  (line 44-46), and in the two exception handlers:

  ```python
  logger.exception("Failed to fetch membership for %s", email)
  ```

  (line 48) and

  ```python
  logger.exception("Unexpected error fetching membership for %s", email)
  ```

  (line 51).

- The precedent inside the same function (`ticket_api.py:26-30`):

  ```python
  if not self.base_url:
      # Global state, identical for every user, so the email adds no
      # diagnostic value here — and keeps it out of the logs.
      logger.debug("Membership API not configured; skipping lookup")
      raise MembershipAPIError
  ```

- The client's only knowledge of the user is the `email` parameter —
  there is no user id in scope, so the fix is to drop the address, not
  substitute an id (changing the function signature is out of scope).
- Tests: `tests/integration/links/test_ticket_api.py` exists and does
  not currently assert on log content (no `caplog` usage), so the
  message changes cannot break existing assertions.

## Commands you will need

| Purpose | Command | Expected on success |
| --- | --- | --- |
| Install | `mise install && poetry install` | exit 0 |
| These tests | `mise run test:int -- tests/integration/links/test_ticket_api.py` | all pass |
| All Py tests | `mise run test:py` | all pass |
| CI-style checks | `mise run check` | exit 0 |

## Scope

**In scope** (the only files you should modify):

- `src/ludamus/links/ticket_api.py`
- `tests/integration/links/test_ticket_api.py`

**Out of scope** (do NOT touch, even though they look related):

- The `fetch_membership_count` signature and its callers
  (`mills/enrollment.py`, `inits/`) — the API contract stays.
- Other loggers in the codebase — this plan is scoped to the one file
  the audit verified; a broader PII-in-logs sweep is a separate effort.
- `edges/settings.py` LOGGING config.

## Git workflow

- Branch off the default branch; commit style example:
  `fix(links): drop user e-mail from membership lookup logs`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Remove the e-mail from all three log calls

In `src/ludamus/links/ticket_api.py` change the three calls to:

```python
logger.info("Fetched membership count %d", membership_count)
```

```python
logger.exception("Failed to fetch membership")
```

```python
logger.exception("Unexpected error fetching membership")
```

The stack trace and exception message keep their diagnostic value; the
count is the operational signal on success.

**Verify**:
`grep -n "email" src/ludamus/links/ticket_api.py` → the only matches
are the function parameter, the `params={"email": email}` request line,
and the comment block — none inside a `logger.` call.

### Step 2: Add a caplog regression test

In `tests/integration/links/test_ticket_api.py`, following the file's
existing test style, add a test that runs a successful lookup and a
failing lookup with pytest's `caplog` fixture and asserts the e-mail
address string does not appear in `caplog.text` for either. Use the
same request-stubbing approach (the `responses` library) as the
surrounding tests.

**Verify**:
`mise run test:int -- tests/integration/links/test_ticket_api.py` →
all pass, including the new test.

### Step 3: Full gate

**Verify**: `mise run check` → exit 0 and `mise run test:py` → all
pass.

## Test plan

- New: caplog assertion that no e-mail address is logged on the
  success path or the `RequestException` path — the regression this
  plan exists for. Model on the existing tests in
  `tests/integration/links/test_ticket_api.py` (integration test, per
  the repo rule that `links` code gets integration tests).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] No `logger.*` call in `src/ludamus/links/ticket_api.py`
  references `email`
- [ ] `mise run test:py` exits 0, including the new caplog test
- [ ] `mise run check` exits 0
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The excerpts no longer match (drift).
- You find other tests asserting on these exact log messages (none
  exist at planning time) — align them, but if that pulls in files
  outside the in-scope list, report first.
- You are tempted to hash the e-mail or thread a user id through the
  signature "while you're here" — don't; that changes the pacts
  protocol and callers, and was deliberately excluded.

## Maintenance notes

- If support ever needs to correlate membership lookups to users, add
  a user id parameter through the protocol and callers in a dedicated
  change — do not reintroduce the address.
- A broader sweep for PII in other loggers (grep for `%s` log calls
  passing user fields) was deferred; the audit only verified this
  file.
- Reviewers should scrutinize: exception context is still logged via
  `logger.exception` (stack trace preserved).
