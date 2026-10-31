# Evals: Django (old) vs rat-stack + Foldkit (new)

Same seeded database (`dev.e2e.sqlite3`), same machine, same port, one process each (Django: gunicorn 1 worker × 2 threads with WhiteNoise; new: one Node process). Numbers come from `mise run experiment:evals`; rerun it to refresh this file. A ratio below 1 means the new app is smaller or faster.

_Benchmarks have not been run yet (`bench-old.json` / `bench-new.json` missing)._

## Acceptance: the existing Playwright suite

_No e2e matrix yet (`e2e-matrix.json` missing)._

## Differential tests of the ported rules

_No differential summary yet (`differential.json` missing)._

## Code size

Non-blank lines. The whole-application row compares a complete product with a slice and is there for scale only; the per-page rows compare like with like.

| Area | old files | old lines | new files | new lines | ratio |
| --- | ---: | ---: | ---: | ---: | ---: |
| whole application (all source, templates, client; tests excluded) | 1034 | 104987 | 46 | 3277 | 0.03× |
| events feed page | 7 | 311 | 0 | 0 | 0.00× |

