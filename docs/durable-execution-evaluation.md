# Durable execution & in-system cron: Absurd vs DBOS

**Status:** DECIDED — DBOS, implemented. `inits/dbos_scheduler.py` hosts the
durable offer timers plus `@DBOS.scheduled` cron workflows (offers sweep every
5 min, printables reminders daily); `ServiceInjectionMiddleware` launches DBOS
per serving process (fail-soft, on a daemon thread); the system DB defaults to
the app Postgres (SQLite in dev); `OFFER_EXPIRY_SCHEDULER` defaults to `dbos`
with the management commands kept as the manual floor. Bake-off that informed
the call: [§8](#8-bake-off-results-empirical--this-spike).

**Question:** We want scheduled jobs ("crons") handled *inside the system*
rather than relying on hand-wired host cron. Should we build on **DBOS**
(already a dependency) or adopt **Absurd** (`earendil-works/absurd`)?

**Recommendation:** **Use DBOS.** For our requirements it isn't close — see
[§6](#6-recommendation). Absurd is impressive but a net-new, v0.x, second
durable system whose one advantage (minimalism) we'd pay for with a new
Postgres extension and a new worker process.

---

## 1. Why this even matters right now

Two facts from the codebase make this urgent rather than academic:

- **Nothing schedules our periodic jobs in the committed deployment.** Prod
  runs exactly one long-lived app process — gunicorn `web` (4 workers × 2
  threads). There is **no worker, no scheduler, and no host-cron/systemd unit
  committed** anywhere (`docker/compose/prod.yaml`, `docker/mise.toml`,
  `docs/DEPLOYMENT.md`). So `expire_offers` and the new
  `send_printables_reminders` are effectively **dead code in prod** until
  someone wires cron by hand. "Crons in the system" closes a real gap.
- **DBOS is already here.** It's a locked dependency (`dbos = ">=2.23.0"`,
  `dbos-2.26.0` in the lock), wired behind `OfferExpirySchedulerProtocol`,
  launched lazily in `inits/dbos_offer_scheduler.py`, and covered by tests
  (`test_dbos_smoke.py`, `test_dbos_offer_scheduler.py`). It's opt-in and
  **off by default** (`OFFER_EXPIRY_SCHEDULER=cron`).

So one contender is already integrated; the other would be introduced from
zero.

## 2. What we actually need (requirements, from the code)

Grounded in `mills/enrollment.py`, `inits/dbos_offer_scheduler.py`, the
management commands, and the deployment files:

| # | Requirement | Detail |
| --- | --- | --- |
| R1 | **Periodic sweeps** | `send_printables_reminders` (daily, 2-day lead — coarse) and `expire_offers` (every few min). Both already idempotent via DB columns. |
| R2 | **Per-item durable timer** | Offer/seat-hold expiry arms a timer at `now + offer_claim_window` (per-category, e.g. 24h) individually per offer (`enrollment.py:113,206`). "Sleep until *this* deadline, then act." The real durable-execution workload. |
| R3 | **Restart survival** | Deadlines must survive worker recycling and redeploys. Today met at the data layer (`offer_expires_at` on the row) even without a broker. |
| R4 | **Coordination under 4 gunicorn workers** | Any in-process scheduler is instantiated up to 4×. Duplicate firings are *tolerable* (actions are status+token+deadline guarded and idempotent), but we don't want 4× redundant execution every tick. |
| R5 | **Timing precision** | R2 wants low latency (a lapsed seat should roll to the next waiter fast). R1 does not. Correctness is deadline-exact regardless of scheduler cadence (guards at `enrollment.py:220,254`). |
| R6 | **Dev ergonomics** | Kill the `sqlite:///dbos_sys.sqlite` dev wart and the "silently does nothing until an operator adds cron" gap. |

**Key insight:** our jobs are already **idempotent and race-safe**, so we need
*coordination* (fire once per tick, ideally) but not hard distributed
exactly-once for correctness. That materially lowers the bar — and both tools
clear it — but it's the difference between "clean" and "works but sloppy."

## 3. The two contenders at a glance

| | **DBOS** (`dbos-transact-py`) | **Absurd** (`earendil-works/absurd`) |
| --- | --- | --- |
| What it is | Durable workflows on Postgres, batteries-included | Durable queue + checkpoints on Postgres, deliberately minimal |
| In our stack? | **Yes** (dep, wired, tested) | No — net-new dependency |
| Version / age | v2.26, ~2 yrs, active daily | **v0.4.0, ~8 months**, tagline "An experiment in durability" |
| License | MIT | Apache-2.0 |
| Backing | DBOS, Inc. (funded company, paid Cloud/Conductor) | Armin Ronacher / Earendil "sidequest", runs it in prod, AI-assisted |
| Stars | ~1,470 | ~2,250 |
| **Built-in cron** | **Yes** — `@DBOS.scheduled("cron")` | **No** — use `pg_cron` or an app-side loop |
| Cross-process fire-once | **Yes** — Postgres idempotency key (schedule + tick) | No native dedup; at-least-once, "overlapping execution possible" |
| Storage | System tables; **can share app Postgres** (schema `dbos`) | One SQL schema in app Postgres; 5 tables/queue |
| Worker process required? | No — runs in the web process | **Yes** — long-lived polling worker (new compose service) |
| Python/Django glue | Official (thin) Django `AppConfig.ready()` guidance | None documented |

## 4. The cron question, specifically

This is the crux of "crons in the system," and it's where the two diverge
hardest.

**DBOS** — first-class. `@DBOS.scheduled('0 3 * * *')` on a workflow;
`croniter` syntax (5–6 fields, optional seconds). Across our 4 gunicorn
workers it fires **exactly once per tick**, not 4×: DBOS builds an idempotency
key from *schedule-name + scheduled-time* in the shared system DB, so every
worker's scheduler loop races to start it but only one wins. That's the
verified, direct answer to R4 — with **zero new infrastructure** (it runs
inside gunicorn).

**Absurd** — "does not include built-in cron support" (their words). Two
documented paths, both with a cost for us:

1. **`pg_cron`** — a Postgres *extension*. Our prod DB is
   `postgres:16-alpine`, which does **not** ship `pg_cron` (it needs
   `shared_preload_libraries` and a custom image). So this path means changing
   our database image and operational surface — a real infra addition, not a
   code one.
2. **App-side scheduler loop** that evaluates cron expressions and calls
   `spawn` with an idempotency key. That's re-implementing what DBOS gives for
   free, and it still needs a long-lived process to run the loop.

Either way Absurd also needs a **dedicated worker** process (pull-based; the
sync worker is a blocking loop you'd run as a separate container/management
command). That's a new `worker` service in `prod.yaml` we don't have today.

**Net:** for the literal ask — crons in the system — DBOS delivers it
in-process with built-in, fleet-safe scheduling; Absurd requires a Postgres
extension (or a hand-rolled loop) **and** a new worker process.

## 5. Fit against our requirements

| Req | DBOS | Absurd |
| --- | --- | --- |
| R1 periodic sweeps | `@DBOS.scheduled` ✅ | pg_cron/app-loop + worker ⚠️ |
| R2 per-item durable timer | Already implemented (`DBOS.sleep`) ✅ | `sleep_until` step; re-implement wiring ⚠️ |
| R3 restart survival | Checkpointed system DB; auto-recovers PENDING ✅ | Lease-based claim + checkpoints ✅ |
| R4 coordinate 4 workers | Idempotency-key fire-once ✅ | At-least-once, tolerate overlap ⚠️ |
| R5 precision | Exact per-item timer ✅ | Exact via `sleep_until` ✅ |
| R6 dev ergonomics | System DB → app Postgres kills sqlite wart; self-schedules ✅ | Single-Postgres ✅, but adds worker + extension ⚠️ |

Both are *technically* capable. DBOS wins on **integration cost, cron
ergonomics, and coordination**; Absurd's only edge is philosophical
minimalism, which our already-present DBOS integration cancels out.

## 6. Recommendation

**Adopt DBOS as the in-system scheduler.** Concretely:

1. Move `expire_offers` and `send_printables_reminders` to `@DBOS.scheduled`
   workflows (keep the management commands as manual/backfill entry points —
   they're the idempotent floor and are useful for ops/tests).
2. **Point `DBOS_SYSTEM_DATABASE_URL` at the app Postgres** (schema-namespaced)
   in every environment. Removes the dev sqlite wart (R6) and gives real
   cross-worker coordination (R4).
3. Flip the default so DBOS is the standard path, and **launch DBOS at app
   startup** (Django `AppConfig.ready()`) instead of lazily on first
   `schedule_expiry`, so scheduled jobs run regardless of request traffic.

Rationale in one line: DBOS is already paid for, gives built-in fleet-safe
cron with no new infrastructure, and simultaneously upgrades offer-expiry from
the coarse cron-floor to exact per-item timers. Absurd would add a dependency,
a worker process, and a Postgres extension to end up in the same place, while
being an 8-month-old v0.x "experiment."

**When Absurd *would* win:** if we had decided to **rip DBOS out** and
standardize on "just one SQL schema, tiny SDK, no magic," and were willing to
run a worker and pg_cron. That's a platform migration, not a cron ticket — and
not justified by current needs.

## 7. Risks to validate before committing (small spike)

DBOS is the recommendation, but two things the research flagged as *unverified
for our exact setup* must be checked with a throwaway spike, not taken on
faith:

- **Pre-fork gunicorn + `DBOS.launch()`.** Launching in `AppConfig.ready()`
  means each of the 4 forked workers launches its own DBOS instance/scheduler
  thread. Cross-worker *scheduling* dedup is documented to work via the system
  DB, but forking after opening DB connections/threads can be fragile.
  Validate: run 4 workers locally against Postgres, confirm a `*/1 * * * *` job
  fires once/minute total (not 4×), and confirm no fork-related connection
  errors. Consider distinct **executor IDs** per worker.
- **Fleet-wide crash recovery is a paid feature.** OSS DBOS recovers a
  process's own PENDING workflows on *its* restart; automatic recovery of a
  *permanently dead* worker's in-flight workflows across the fleet needs
  **DBOS Conductor** (commercial). For us this is low-risk: the offer deadline
  also lives on `offer_expires_at`, so keeping `expire_offers` as a periodic
  belt-and-suspenders sweep covers any missed timer. Decide explicitly to keep
  that floor.

Also mind DBOS's **workflow-versioning** constraint on deploys (in-flight
workflows are tagged with an app version; changing workflow code can strand
them → blue-green drain). For daily/short-lived jobs this is negligible;
worth knowing for the offer timer.

## 8. Bake-off results (empirical — this spike)

I built and ran the *same* job — "fire `send_due_reminders` on a schedule" —
in both, against a real local Postgres 16 and (for DBOS) sqlite, on this
repo's Python 3.14. Standalone scripts, the work function stubbed to a log so
firings can be counted. Findings:

- **DBOS `@DBOS.scheduled` works out of the box on sqlite** (the repo's current
  dev/test DB): a 1-second schedule fired **7 times in 7 seconds, exactly once
  per tick**. Wiring cost: a decorator + `DBOS.launch()` — ~5 lines. No queue
  to create, no schema to vendor, no worker process.
- **Absurd's spawn + idempotency-key dedup works exactly as advertised.** Two
  concurrent "cron-loop" processes (simulating replicas) spawning every second
  with `idempotency_key=f"...|{tick}"` produced **7 tasks for 7 ticks — no
  double-spawn.** That's the coordination primitive you'd rely on, and it held.
- **Both were blocked on the *same* driver bug on Python 3.14**, which is the
  headline finding. `psycopg3` (3.2.13 and 3.3.4) on Python 3.14.6 returns
  **`bytes` for `text` columns** (`select 'hello'::text` → `b'hello'`). It
  surfaced differently in each: **DBOS crashed at launch** (SQLAlchemy's
  psycopg dialect runs a regex on the bytes `version()` string) — loud and
  obvious. **Absurd silently skipped every task** (the claimed `task_name`
  came back as `b't1'`, missing the str key in its handler registry) — a
  silent no-op that took DB spelunking to diagnose. Bridging the bytes key
  (`app._registry[b"t1"] = app._registry["t1"]`) made Absurd's handler run, so
  Absurd itself is fine — it's the driver.

Two consequences that matter for the decision:

- **DBOS has a dev escape hatch; Absurd does not.** DBOS runs on sqlite, so it
  works in our existing dev/test setup today (and dodged the psycopg bug).
  Absurd is **Postgres-only**, so on Python 3.14 it can't run *anywhere* until
  the psycopg3 text regression is resolved. For prod, DBOS also needs Postgres
  (sqlite won't coordinate 4 workers), so **the psycopg3/3.14 issue is a live
  prerequisite for either tool's prod path** — verify it against the actual
  deploy image's Python/psycopg build before committing. This is the "validate
  in a spike" caveat made concrete.
- **Absurd's minimalism shifts work onto you, empirically.** For *scheduling*
  specifically it was more scaffolding, not less: vendor a **3,083-line**
  `absurd.sql` as a migration, `create_queue`, register the task, **hand-write
  the cron loop** (it has no scheduler), and run a **separate worker process**.
  DBOS needed a decorator and a launch call. Absurd's design is genuinely
  cleaner to *read* (just tables + SQL), but the wiring surface for this use
  case is larger.

Net: the bake-off **reinforces DBOS** for our scheduling need, while giving
Absurd real credit — its dedup worked first try and the model is transparent.
The one hoped-for Absurd win ("simpler, less to wire") did not materialise for
cron, because cron is exactly the batteries it deliberately omits.

Spike artifacts (throwaway, on branch `spike/absurd-vs-dbos-cron`): DBOS
`@DBOS.scheduled` script, Absurd task+worker+cron-loop scripts, and the raw
firing logs.

## 9. Appendix — sources

- Absurd: <https://earendil-works.github.io/absurd/> (concepts, patterns/cron,
  database, comparison, python SDK), <https://github.com/earendil-works/absurd>,
  Ronacher "Absurd In Production"
  <https://lucumr.pocoo.org/2026/4/4/absurd-in-production/>
- DBOS: <https://docs.dbos.dev> (architecture, scheduled-workflows, queues,
  configuration, workflow-recovery, integrations/django),
  <https://github.com/dbos-inc/dbos-transact-py>
- Codebase: `inits/dbos_offer_scheduler.py`, `links/scheduler.py`,
  `pacts/enrollment.py:242`, `mills/enrollment.py:89-271`,
  `inits/services.py:219-235`, `edges/settings.py:57-62,417-418`,
  `docker/compose/prod.yaml`, `docker/mise.toml:34-54`.
