# Plan 001: Key throttles on a trusted X-Forwarded-For entry

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to
> the next step. If anything in the "STOP conditions" section occurs,
> stop and report — do not improvise. When done, update the status row
> for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 0bec0f2..HEAD -- src/ludamus/gates/web/django/helpers.py`
> If the file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `0bec0f2`, 2026-07-09

## Why this matters

Two abuse throttles key on the client IP returned by `get_client_ip`:
the anonymous session-proposal rate limit and the encounter RSVP
throttle. The helper returns the **leftmost** entry of the
`X-Forwarded-For` header, which is fully client-controlled: an
unauthenticated attacker sends a different fake value per request and
gets a fresh throttle bucket every time, defeating both limits. That
enables spamming anonymous session proposals (each creates DB rows) and
RSVP flooding. Production runs behind exactly one reverse proxy
(nginx/Caddy per `docs/DEPLOYMENT.md`), which appends the real peer IP
as the **rightmost** entry — so the rightmost entry is the trustworthy
one.

## Current state

- `src/ludamus/gates/web/django/helpers.py:11-14` — the vulnerable
  helper:

  ```python
  def get_client_ip(request: HttpRequest) -> str:
      if forwarded := request.META.get("HTTP_X_FORWARDED_FOR", ""):
          return str(forwarded).split(",", maxsplit=1)[0].strip()
      return str(request.META.get("REMOTE_ADDR", ""))
  ```

- Consumers (do not change their call sites):
  - `src/ludamus/gates/web/django/chronology/views.py:859-861` —
    anonymous proposal rate limit:

    ```python
    if not getattr(request.user, "is_authenticated", False):
        ip = get_client_ip(request)
        if not check_proposal_rate_limit(request.di.cache, ip, event.pk):
    ```

  - `src/ludamus/gates/web/django/notice_board/views.py:360-362` — RSVP
    throttle ("1 per minute per IP"):

    ```python
    # Throttle: IP-based, 1 per minute
    ip_address = _get_client_ip(request)
    if uow.encounter_rsvps.recent_rsvp_exists(ip_address):
    ```

- The rate-limit logic itself is sound and out of scope:
  `check_proposal_rate_limit` in `src/ludamus/mills/legacy.py:452-462`
  and `recent_rsvp_exists` in
  `src/ludamus/links/db/django/repositories/notice_board.py:108-113`.
- Deployment topology (`docs/DEPLOYMENT.md:94-98`): the web service
  binds to `127.0.0.1:8000`; a single reverse proxy fronts it and sets
  `X-Forwarded-Proto` (Django trusts it via `SECURE_PROXY_SSL_HEADER`
  at `src/ludamus/edges/settings.py:306-308`). With one trusted proxy
  that appends to `X-Forwarded-For`, the rightmost entry is the TCP
  peer the proxy actually saw; every entry left of it is attacker
  input.
- Existing tests that pin current behavior:
  - `tests/integration/web/notice_board/test_rsvp_action.py:82` —
    `test_rsvp_with_x_forwarded_for` sends a single-entry
    `HTTP_X_FORWARDED_FOR="203.0.113.50"`; with a one-entry header
    leftmost == rightmost, so it must stay green unchanged.
  - `tests/integration/web/notice_board/test_rsvp_action.py:96` —
    `test_ip_throttle` uses `REMOTE_ADDR` only.
  - `tests/integration/web/chronology/test_propose_session.py` covers
    the proposal rate limit.

## Commands you will need

| Purpose         | Command                          | Expected on success |
|-----------------|----------------------------------|---------------------|
| Install         | `mise install && poetry install` | exit 0              |
| All Py tests    | `mise run test:py`               | all pass            |
| One test file   | `mise run test:int -- <path>`    | all pass            |
| CI-style checks | `mise run prcheck`               | exit 0              |

## Scope

**In scope** (the only files you should modify):

- `src/ludamus/gates/web/django/helpers.py`
- `tests/integration/web/notice_board/test_rsvp_action.py`
- `tests/integration/web/chronology/test_propose_session.py`

**Out of scope** (do NOT touch, even though they look related):

- The consumers listed above — their call sites are correct.
- `src/ludamus/mills/legacy.py` (`check_proposal_rate_limit`) and
  `src/ludamus/links/db/django/repositories/notice_board.py`
  (`recent_rsvp_exists`) — the keying, not the limiting, is the bug.
- `src/ludamus/edges/settings.py` — no new settings; one known proxy
  makes the rightmost-entry rule deterministic.

## Git workflow

- Branch off the default branch; short imperative commit subject,
  conventional prefix matching `git log` style, e.g.
  `fix(web): key throttles on the proxy-appended client IP`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Take the rightmost X-Forwarded-For entry

In `src/ludamus/gates/web/django/helpers.py`, change `get_client_ip`
to:

```python
def get_client_ip(request: HttpRequest) -> str:
    if forwarded := request.META.get("HTTP_X_FORWARDED_FOR", ""):
        # The rightmost entry is appended by our own reverse proxy;
        # everything left of it is client-supplied and spoofable.
        return str(forwarded).rsplit(",", maxsplit=1)[-1].strip()
    return str(request.META.get("REMOTE_ADDR", ""))
```

**Verify**: `mise run test:py` → all pass (notably
`test_rsvp_with_x_forwarded_for`, which uses a single-entry header).

### Step 2: Add spoof-regression tests

In `tests/integration/web/notice_board/test_rsvp_action.py`, next to
`test_ip_throttle`, add a test that posts two RSVPs whose
`HTTP_X_FORWARDED_FOR` differs only in the client-controlled leftmost
part (e.g. `"1.2.3.4, 203.0.113.50"` then `"5.6.7.8, 203.0.113.50"`)
and asserts the second is throttled (same message/behavior as
`test_ip_throttle`). Model the arrangement on the two existing throttle
tests in that class.

In `tests/integration/web/chronology/test_propose_session.py`, add the
equivalent regression for the anonymous proposal flow: two submissions
with different leftmost XFF but the same rightmost entry — the second
must be rate-limited. Follow the file's existing test structure and the
`assert_response` utility if the surrounding tests use it.

**Verify**:
`mise run test:int -- tests/integration/web/notice_board/test_rsvp_action.py`
→ all pass, including the new test.
`mise run test:int -- tests/integration/web/chronology/test_propose_session.py`
→ all pass, including the new test.

### Step 3: Full gate

**Verify**: `mise run prcheck` → exit 0, and `mise run test:py` → all
pass.

## Test plan

- New: spoofed-leftmost-XFF regression for the RSVP throttle
  (`test_rsvp_action.py`) and for the anonymous proposal rate limit
  (`test_propose_session.py`) — both assert the throttle holds when
  only the client-controlled part of the header varies.
- Existing single-entry XFF and `REMOTE_ADDR` tests must pass
  unchanged.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n "split(" src/ludamus/gates/web/django/helpers.py` shows
  `rsplit(",", maxsplit=1)[-1]` and no leftmost `split(...)[0]`
- [ ] `mise run test:py` exits 0; the two new regression tests exist
  and pass
- [ ] `mise run prcheck` exits 0
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `get_client_ip` no longer matches the excerpt above (drift).
- You find evidence the production proxy chain has more than one hop
  (e.g. a CDN in front of nginx documented somewhere) — the
  rightmost-entry rule would then need a hop count instead; report,
  don't guess.
- `test_rsvp_with_x_forwarded_for` fails after Step 1 — that means the
  test sends a multi-entry header and expectations must be decided by a
  human.
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

- If a CDN or second proxy layer is ever added in front of the current
  reverse proxy, the rightmost entry becomes the *inner* proxy's
  address; `get_client_ip` must then skip a configurable number of
  trusted hops. Revisit this helper in that deployment change.
- Reviewers should scrutinize: no consumer accidentally started passing
  raw header values around; the comment explaining the trust boundary
  survives formatting.
- Deferred: rate limits are still per-IP and can be defeated by an
  attacker with many real IPs; stronger abuse controls (per-account,
  CAPTCHA) were deliberately left out of this plan.
