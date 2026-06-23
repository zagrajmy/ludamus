# Plan 003: Replace Faker("slug") with sequences in test factories (kill flaky CI)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command before moving on. On any STOP condition, stop and
> report. When done, update this plan's row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 337cdde7..HEAD -- tests/integration/conftest.py tests/integration/factories.py`
> Mismatch with "Current state" = STOP.

## Status

- **Priority**: P2 (small, do early — it stabilizes CI for everything else)
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `337cdde7`, 2026-06-10

## Why this matters

`Faker("slug")` draws from a finite word list, so two factory-built objects in
one test can collide on a unique `slug` column and fail the test
nondeterministically. This exact failure already happened and was fixed
piecemeal: commit `bde5be84` ("fix(flaky): AnonymousUserFactory slug collision
via faker.word()") switched one factory to a deterministic value. Eight more
`Faker("slug")` declarations remain in `tests/integration/conftest.py`. Each
is a latent flaky-CI bug; flaky CI wastes a re-run per occurrence and erodes
trust in red builds (the repo history shows "Re-trigger CI to clear flaky e2e
run" commits).

## Current state

`tests/integration/conftest.py` declares factory_boy factories for the whole
integration suite. Eight `slug = Faker("slug")` occurrences, at lines
83 (EventFactory), 108 (VenueFactory), 118, 128, 146, 157, 166, 192 (run
`grep -n 'Faker("slug")' tests/integration/conftest.py` to enumerate; line
numbers may have drifted slightly).

Excerpt (`tests/integration/conftest.py:78-90`):

```python
class EventFactory(DjangoModelFactory):
    class Meta:
        model = Event

    name = Faker("sentence", nb_words=4)
    slug = Faker("slug")
    description = Faker("text")
    sphere = SubFactory(SphereFactory)
```

The proven in-repo pattern for the fix (from commit `bde5be84`, in
`tests/integration/factories.py` — read it with
`git show bde5be84 -- tests/integration/factories.py` if you want the exact
diff) is `factory.Sequence`.

Important: pytest-factoryboy may expose these factories as fixtures; tests may
also pass explicit `slug=` values — those are unaffected by changing the
default declaration.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Integration tests | `poetry run pytest tests/integration -q` | all pass |
| Full suite | `mise run test` | all pass |
| Lint | `mise run prcheck` | exit 0 |

## Scope

**In scope**:
- `tests/integration/conftest.py` (the eight `slug = Faker("slug")` lines)
- `tests/integration/factories.py` ONLY if `grep -n 'Faker("slug")'` finds occurrences there too

**Out of scope**:
- Other `Faker(...)` fields (`name`, `description`, usernames…) — they don't
  populate unique columns; leave them.
- e2e fixtures under `tests/e2e/`.
- Production slug generation (`make_unique_slug` in gates) — unrelated.

## Git workflow

- Branch: `advisor/003-deterministic-factory-slugs`
- One commit, message in repo style, e.g. "fix(flaky): deterministic factory slugs via Sequence".
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Replace each occurrence

For each factory with `slug = Faker("slug")`, replace with a sequence that is
unique per factory class, e.g. for `EventFactory`:

```python
slug = Sequence(lambda n: f"event-{n}")
```

Use a per-factory prefix derived from the model name (`venue-{n}`,
`space-{n}`, …) so cross-factory slugs never collide either and test output
stays readable. Check what `factory` import alias the file already uses
(`from factory.django import DjangoModelFactory`, `Faker`, `SubFactory` are
imported individually — add `Sequence` to the same import style rather than
importing the whole module, matching the file's conventions).

**Verify**: `grep -cn 'Faker("slug")' tests/integration/conftest.py` → 0 matches.

### Step 2: Run the suite

**Verify**: `poetry run pytest tests/integration -q` → all pass. Then
`mise run test` → all pass; `mise run prcheck` → exit 0.

If a test fails because it asserted a slug *format* (e.g. expects faker-style
words), update that single assertion to use the object's actual slug — tests
must not depend on default factory values. If more than 3 tests assert slug
formats, STOP and report (the change is noisier than planned).

## Test plan

No new tests — this plan removes nondeterminism from existing ones. The gate
is the full suite passing, twice in a row if cheap:
`poetry run pytest tests/integration -q` run 2× → same result.

## Done criteria

- [ ] `grep -rn 'Faker("slug")' tests/integration/` returns no matches
- [ ] `mise run test` exits 0
- [ ] `mise run prcheck` exits 0
- [ ] Only in-scope files modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

- More than 3 tests assert on the faker-generated slug format.
- A factory's slug is used as a stable cross-test identifier (same slug
  expected in two different test modules) — would indicate hidden coupling.

## Maintenance notes

- Reviewers: confirm no new factory reintroduces `Faker("slug")`; consider a
  ruff/ast-grep rule later (`sgconfig.yml` exists at repo root) to ban it.
- This complements, not replaces, the open flaky-e2e work; e2e slug
  generation lives separately under `tests/e2e/`.
