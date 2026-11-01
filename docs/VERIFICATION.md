# Verification beyond example tests

Example tests check the cases someone thought of. The tools below check rules:
each one states a promise the code makes and lets a machine hunt for a case
that breaks it. Each layer of the code gets the tool that reaches it best.

| Layer | Tool | What it checks | Where | Run |
| --- | --- | --- | --- | --- |
| Pure logic (`specs/`, pure `mills/` helpers) | Hypothesis, CrossHair as an optional backend | The real Python, on generated inputs | `tests/unit/test_*_properties.py` | `mise run test:py`, `mise run test:props:crosshair` |
| Repositories and services on a database | Hypothesis | The real code against SQLite or Postgres | `tests/integration/**/test_*_properties.py` | `mise run test:py` |
| Locks and transactions | Bend | A model of the code at transaction grain: proofs for every run, and traces for known races | `formal/<area>/` | `mise run formal` |
| Model against code | Hypothesis, with Bend compiled to JS | The same steps run through the real view and the model must agree | `tests/integration/web/chronology/test_seats_model_differential.py` | `mise run test:py` |
| Pages | Bombadil | Random browsing of the seeded app, against properties of what the pages show | `tests/bombadil/` | `mise run test:bombadil` |

## Pick the tool by the question

- **Does this function do the right thing for every input?** If it is pure,
  write a Hypothesis property next to its unit tests. State a rule, not a
  second copy of the function: "never seats more than the seats left" is a
  rule; re-walking the queue in the test is a copy, and it passes whenever the
  code does. Integer-heavy code is worth a run with
  `HYPOTHESIS_PROFILE=crosshair`, which solves for the edge instead of
  guessing it.
- **Does it hold when two requests interleave?** No test runner forces the
  interleaving. Model the transactions in Bend (one action per stretch that
  runs before another transaction can commit) and either prove the rule for
  every run or record the race as a finding. The `verify-enrollment-seats`
  skill walks through writing and updating these models.
- **Does the model still describe the code?** Compile it with
  `bend x.bend -o x.gen.mjs` and drive the real code and the model with the
  same Hypothesis-generated steps, as the seats differential test does.
- **Does the page tell the truth?** Add a Bombadil property to
  `tests/bombadil/enrollment.ts`. Properties see the DOM on every state
  Bombadil reaches; `actions(...)` steers it toward the controls that matter.

## Known bugs stay visible until fixed

A test or model that exposes a bug on `main` is kept, not skipped:

- A Bend finding (`formal/<area>/finding_*.bend`) proves that the model can
  reach a trace that breaks the rule. That convicts the model; it says the
  code has the bug only as far as the model is true to the code, so the
  findings table below says which ones were also reproduced against the real
  code. A finding checks while its trace exists and stops checking once the
  code and model are fixed; then delete it and prove the rule in `LAWS.bend`.
- A Hypothesis property for an open bug is marked
  `@pytest.mark.xfail(strict=True, raises=AssertionError, reason="finding: …")`.
  It turns red when the bug is fixed, so the fix removes the marker.

## Open findings

| Area | Finding | Evidence |
| --- | --- | --- |
| Enrollment | A held or offered seat gets past the conflict check, so a person ends up confirmed in two overlapping sessions | Reproduced against the real views; `formal/enrollment/finding_offered_seat.bend` |
| Enrollment | Two enrolls at once double-book a person; each locks only its own session | `formal/enrollment/finding_two_requests.bend` |
| Enrollment | Two enrolls at once seat more people than the owner holds passes | `formal/enrollment/finding_allowance_race.bend` |
| Programme | Two accepts at once put two proposals in one room and slot | `formal/programme/finding_two_accepts.bend` |
| Programme | A double-submitted accept answers with a 500 | `formal/programme/finding_double_submit.bend` |
| Announcements | Overlapping sweeps announce an event twice (also printables reminders) | `formal/announcements/finding_overlapping_sweeps.bend` |

## Limits

- Bend models are hand-written. The differential test ties `seats.bend` to the
  code; the other models are tied only by review and the skill's trigger paths.
- CrossHair costs about two seconds per example here, so its CI job is
  advisory and runs only the window-policy properties.
- Bombadil explores at random: a clean run is a sample, not a proof, and its
  CI job is advisory. It starts signed in as `e2e-party-host` and stays on
  `/event/*` and `/dashboard/*`.
