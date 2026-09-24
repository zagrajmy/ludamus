---
title: 'Local Playwright server reuse silently skips the client-coverage CI-parity check'
severity: 'minor'
---

## Expected Behavior

Reusing a manually started local dev server for repeated e2e test runs
should either faithfully reproduce CI's pass/fail outcome, or clearly warn
when it can't.

## Current Behavior

`playwright.config.ts` sets `reuseExistingServer: !isCI`, so a manually
started `mise run test:e2e:serve` background process gets silently reused by
every subsequent `npx playwright test ...` run. Locally this hid a real bug:
`global-teardown.ts`'s "Client coverage did not reach the TypeScript sources"
check (a genuine CI-parity guard against exactly this kind of stale-server
reuse) never tripped across ~6 local runs of a single spec, yet failed
immediately on the very next real CI run of the same commit. Root cause was
unrelated to server staleness in the end (a Vite-auto-named `chunk-*.js`
carrying no sourcemap, first executed because a newly-fixed spec finally
exercised the code path that loads it) — but the local setup could not have
caught it either way, since reusing the server means the coverage/sourcemap
pipeline this check exists to validate never runs the same way CI runs it.

Reproducing needed the *exact* CI invocation: `CI=true mise run test:e2e --
shard=3/3` (matching `.github/workflows/ci.yml`'s
`mise run test:e2e -- --shard=N/total`), not a single-spec targeted run —
`CI=1 npx playwright test <one spec>` alone (fresh server, still) did not
reproduce it either; only running the full shard with `mise run test:e2e`
(which forces `reuseExistingServer: false` via `CI=true` and lets the
coverage cache accumulate across every file in the shard) did.

## Possible Solution

A note in `docs/agents/sandbox.md` or the e2e docs: when chasing an e2e
failure that only shows in CI and never locally, try the exact
`CI=true mise run test:e2e -- --shard=N/total` invocation (fresh server, no
`reuseExistingServer` shortcut) before concluding it's environment-specific
or unreproducible.

## Minimal Reproducible Example

1. Start \`mise run test:e2e:serve\` in the background and leave it running.
2. Repeatedly run a single spec against it with \`npx playwright test\`.
3. Separately, run \`CI=true mise run test:e2e -- --shard=N/total\` for the
   same spec's shard.
Step 2 can pass every time while step 3 fails on the coverage/sourcemap
check, with no other signal that the two are exercising different code paths.

## Context

Hit while root-causing PR #911 (Parley), fixing a genuinely different
\`test-e2e (3)\` failure than the one this uncovered.
