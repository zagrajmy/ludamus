<!-- markdownlint-disable -->

# TypeScript Standards Audit — 2026-06-19

Audit of this repository's TypeScript against the adopted external standard in
[`docs/standards/typescript.md`](../standards/typescript.md) (source: gist by
[@dmmulroy](https://github.com/dmmulroy)). This is a **documentation-only**
report: it records findings and recommends fixes. It changes no source code.

## Scope

The TypeScript surface here is small and entirely browser-side glue plus
end-to-end tests. There is **no Node/server TypeScript**, no domain layer in TS
(the domain lives in Python under `src/ludamus/`), no schema library, no
dependency-injection framework, and no `Result`/`Effect` machinery in TS.

Reviewed (line counts via `wc -l`):

| Area | Files | Lines | Notes |
| --- | --- | --- | --- |
| Client modules (`src/ludamus/client/src/*.ts`) | 12 | 1629 | Progressive-enhancement DOM scripts, no framework |
| Client build config (`src/ludamus/client/vite.config.ts`) | 1 | 62 | Vite + Tailwind |
| E2E tests (`tests/e2e/tests/**/*.ts`) | 14 | ~3900 | Playwright specs (`panel.spec.ts` alone is 2386) |
| E2E config (`tests/e2e/playwright.config.ts`) | 1 | 106 | |
| One-off repro script (`scripts/reproduce-ios-modal-bugs.ts`) | 1 | 375 | Playwright repro, not shipped |

Largest client modules: `session-filters.ts` (423), `modal.ts` (365),
`timetable.ts` (239), `encounter-form.ts` (112), `confirm.ts` (108).

Tooling that actually runs (from `mise.toml` and `.github/workflows/ci.yml`):

- **Type check:** `tsc --noEmit` (`mise run ts-check` → `npm run typecheck`).
- **Format:** Prettier 3.8.1 (`prettier --write src`), `.prettierrc` has
  `proseWrap: "always"` + the Tailwind plugin.
- **CI `frontend-analysis` job:** runs `fallow` (dead-code / duplication /
  complexity report) and is **non-blocking** (`continue-on-error: true`).
- **No oxlint, no Biome, no ESLint** anywhere in the repo. The standard
  repeatedly references `oxlint`; that lints nothing here today.

### Material mismatch between the standard and this codebase

The standard targets server-side / domain-heavy TypeScript: errors-as-values,
schema parsing at boundaries, branded domain types, adapters/services with DI,
sagas, idempotency, SQLite-backed tests, `fast-check`. **Almost none of that
problem space exists in this repo's TS.** The TS here is thin imperative-shell
DOM code whose "domain" is the DOM and whose "boundary" is `data-*` attributes
the Django templates render. Many standards are therefore **N/A**, and that is
the honest headline, not a failing grade. The standards that *do* apply are the
TypeScript-style/safety, module, import, and comment rules — and the codebase is
already reasonably close on most of them.

## Per-standard findings

Status key: ✅ compliant · ⚠️ partial · ❌ violated · — N/A for this codebase.

| # | Standard (section) | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Decision priority / adapt to existing conventions | ✅ | TS consistently follows one local convention: guard-and-return DOM lookups, event delegation, `data-*` as the boundary. No competing patterns introduced. |
| 2 | Errors as values (`Result`/Effect for expected failures) | — | No `Result`/Effect in TS and no expected-failure domain to model; failures are DOM-absent guards (`if (!el) return`). Reasonable for this surface. |
| 3 | Unrecoverable defects may throw / `prelude.ts` helpers (`casesHandled`, `shouldNeverHappen`) | ⚠️ | Throwing is used for genuine invariant breaches: `modal.ts:93`, `session-filters.ts:7,16`. Appropriate. But there is **no `prelude.ts`** and no `casesHandled` for exhaustive unions; switch-like dispatch in `tabs.ts:59-63` and `session-filters.ts:207-214` is `if/else` without exhaustiveness help. |
| 4 | Custom tagged errors with structured fields | ❌ | All throws are bare `new Error("string")` (`modal.ts:93`, `session-filters.ts:7,16`). No `_tag`, no structured/telemetry fields. Low impact at this size, but technically non-conforming. |
| 5 | Sensitive data / `Redacted<T>` / structured tracing | — | Client code handles no secrets and has no tracing layer. `session-card.ts:51,66` use `console.error`; `timetable.ts:190,198` use `alert()` for user-facing failures. No secrets leak. |
| 6 | Parse, don't validate (boundary → domain types) | ⚠️ | `timetable.ts:41-56` `parsePreferredSlots` is a genuine boundary parser (JSON → typed `PreferredSlot[]`, structural narrowing) — good. Elsewhere `data-*` strings are read inline and coerced ad hoc (`parseInt` in `session-filters.ts:222-226`, `Number(...)` in `timetable.ts:137,151`) rather than parsed once into typed values. |
| 7 | Make illegal states unrepresentable / branded & refined types | ❌ | No branded types anywhere. IDs are raw `string` (`assignSessionPk: string`, `timetable.ts:6`), durations raw `number`. Primitives like `spacePk`, `sessionPk`, ISO datetimes flow untyped. |
| 8 | State machines over boolean blindness; no boolean behavior params | ✅ | Module flags use named options objects, not positional booleans: `openModal(id, { updateUrl, replaceHistory })` (`modal.ts:139-142`), `closeModal` (`modal.ts:159-162`). Booleans are predicate returns (`menu.ts:15` `isOpen()`, `event-print.ts:18` `isEditing`). Assign-mode in `timetable.ts` is a small explicit state, not a boolean bag. |
| 9 | Deep modules / deletion test / no shallow pass-through | ✅ | `modal.ts` hides substantial scroll-lock + URL-sync + a11y behavior behind `openModal`/`closeModal` (`modal.ts:365`). `confirm.ts` composes only that public API (`confirm.ts:11`). No pass-through wrapper modules. |
| 10 | OCaml-style domain modules (parsers/combinators per type) | — | No domain value types in TS to build modules around; concepts live in Python. |
| 11 | Application/service modules with constructor DI; avoid `deps` bags | — | No services/DI in browser code; modules are top-level scripts wired on load. Appropriate for progressive enhancement. |
| 12 | Narrow dependency interfaces / adapter reuse audit / ADRs | — | No adapters or repositories in TS. |
| 13 | Repositories return parsed domain types, not raw rows | — | No persistence in TS. |
| 14 | Functional core / imperative shell; thin entrypoints; no duplicated rules | ⚠️ | Code is essentially all imperative shell (correct for DOM glue), but pure logic is not separated into testable functions. e.g. the diacritic-folding `normalizeText` (`session-filters.ts:64-69`) and `formatBytes` (`encounter-form.ts:26-30`) are pure and reusable but trapped inside closures/modules, untested. |
| 15 | Workflows / transactions / idempotency | — | No multi-step workflows; the one network write (`timetable.ts:177`) is a single fire-and-forget POST with UI rollback on failure. |
| 16 | Testing: confidence-oriented, real seams, no module mocks | ✅ | E2E via Playwright through the real app (`tests/e2e/tests/*.spec.ts`); a11y checks in `tests/e2e/tests/helpers/a11y.ts`. No `vi.mock`/`jest.mock` anywhere. |
| 17 | Property tests + `fast-check` arbitraries near domain modules | ❌ | No `fast-check`, no unit/property tests for the pure helpers that would benefit most (`normalizeText`, `formatBytes`, `parsePreferredSlots`, `toLocalDatetimeValue`). Only e2e exists. |
| 18 | Strict tsconfig (`strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, `noImplicitOverride`, `noFallthroughCasesInSwitch`) | ⚠️ | `strict: true` is set (`src/ludamus/client/tsconfig.json:3`, `tests/e2e/tsconfig.json:7`). The **four additional flags the standard names are all missing.** `noUncheckedIndexedAccess` in particular would flag real array/record indexing here (`session-filters.ts:167,191`, `tabs.ts:66`). |
| 19 | Immutable values (`readonly`, `ReadonlyArray`) | ❌ | No `readonly` in client source; mutable module-level `let` state in `timetable.ts:6-9`. Acceptable per the standard's "imperative shell" carve-out, but not following the preference. |
| 20 | Avoid `any`, non-null `!`, `as Type` casts; `as const` ok; SAFETY comments | ❌ | **Biggest concrete gap.** Eight non-null assertions in `timetable.ts` (`:20,:23,:136,:148,:149,:150,:163`) and `encounter-form.ts:80`. ~20 `as Type` casts (e.g. `timetable.ts:32` `as HTMLInputElement`, `:132,:228` `as Element`, `session-filters.ts:8` `return el as T`, `tabs.ts:40,55,56`, `encounter-form.ts:3,6,110`, `session-edit.ts:36,47`). **No SAFETY comments** justify any of them. No `any` found (good). The standard says "Do not use `!`. Branch, parse, or refine instead." |
| 21 | Direct imports; no barrel/`index.ts`; namespace imports for domain modules | ✅ | No barrel files. Imports are direct and named: `confirm.ts:11` `import { closeModal, openModal } from "./modal"`. Aligns with the standard *and* with this repo's CLAUDE.md no-re-export rule. |
| 22 | `import type` / `export type` for type-only imports | ⚠️ | Only one type import exists and it is inline: `vite.config.ts:4` `import { defineConfig, type Plugin }`. Inline `type` qualifier is fine; no violations, but the convention isn't exercised since interfaces are declared locally (`modal.ts:10-23`, `timetable.ts:1-4`). |
| 23 | Precise file names; avoid `utils.ts`/`helpers.ts`/`common.ts` | ✅ | All files are precisely named by feature (`session-filters.ts`, `info-popover.ts`, `event-print.ts`, `django-hmr.ts`). No junk-drawer files. |
| 24 | No top-level side effects outside entrypoints | ⚠️ | Every client module **is** an entrypoint bundle (see `vite.config.ts:44-59` rollup inputs), so module-load side effects (`modal.ts:337-363`, `session-card.ts:72-79`, `session-filters.ts:423`) are by-design entrypoint bootstrap. Defensible, but there is no separation between "module" and "bootstrap" — importing any of these for a test runs its side effects. |
| 25 | Parse config at startup; no scattered `process.env`; typed config | ✅ | Only `process.env` use is `vite.config.ts:33` `process.env.VITE_PORT` in the build entrypoint — exactly where the standard allows it. No `process.env` in client runtime code. |
| 26 | Avoid mutable singletons/global state | ⚠️ | Module-level mutable singletons exist: `timetable.ts:6-9` (`assignSessionPk`, etc.), `modal.ts:28-30` (`scrollLockTargets`, `markedScrollables`, `touchHandlerInitialized`). For single-instance page scripts this is contained, but it is global-ish state the standard discourages. |
| 27 | Inject `Clock`/`Random`; pure core takes explicit `now` | ❌ | `new Date()` is read ambiently inside logic: `timetable.ts:75,83,84,159`, `encounter-form.ts:19`. Not injected, so these paths are not unit-testable without faking globals. |
| 28 | JSDoc on every exported symbol; standard `@param`/`@returns`/`@template` | ❌ | Exports are largely undocumented. `modal.ts:365` exports `closeModal`/`openModal` with **no JSDoc**. `tabs.ts` has a usage block comment but no per-symbol JSDoc; `event-print.ts` and `modal.ts:25` have explanatory comments, not JSDoc. Only narrative comments exist, not the `@param`/`@returns` form the standard mandates. |
| 29 | Comments explain invariants/trade-offs, not obvious code | ✅ | This is a genuine strength. Comments consistently capture *why*: browser-support reasoning (`modal.ts:25,340-342`), re-entrancy safety (`session-card.ts:14-17`), diacritic handling (`session-filters.ts:50-52`), HMR rationale (`vite.config.ts:6-11`). |

Tally: ✅ 8 · ⚠️ 7 · ❌ 6 · — 8 (of 29 checks).

## Findings and recommendations (highest impact first)

### 1. Adopt a TS linter and the standard's extra `tsconfig` flags (quick win, highest leverage)

The standard leans on `oxlint` and strict compiler flags, but the only enforced
TS gate is `tsc --noEmit` with `strict: true` and a non-blocking `fallow`
report. Nothing currently prevents new `!`, `any`, or unsafe casts.

- Add to both `src/ludamus/client/tsconfig.json` and `tests/e2e/tsconfig.json`:
  `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, `noImplicitOverride`,
  `noFallthroughCasesInSwitch`. Expect `noUncheckedIndexedAccess` to surface
  real gaps at `session-filters.ts:167,191`, `tabs.ts:66`, `timetable.ts:139`.
- Introduce `oxlint` (the standard's named linter) or Biome with `no-explicit-any`
  and non-null-assertion rules, and make the CI step blocking. This is the single
  change that keeps the rest of the standard from regressing.

Effort: small config change; medium follow-up to fix what the flags reveal.

### 2. Eliminate non-null assertions and unjustified casts (medium refactor)

Standard 20 is the clearest, most concrete violation: 8 `!` assertions and ~20
`as Type` casts with zero SAFETY comments.

- Replace the `!` cluster in `timetable.ts` (`:20,:23,:136,:148-150,:163`) and
  `encounter-form.ts:80` with explicit guards that return early or throw a
  tagged error, mirroring the existing `getDialog` pattern in `modal.ts:90-96`.
- For unavoidable DOM-narrowing casts (`event.target as Element`), prefer
  `instanceof` refinement (already done well in `modal.ts:214-219`,
  `confirm.ts:54`, `session-card.ts:41-42`) and apply it consistently in
  `timetable.ts:132,228`, `tabs.ts`, `session-edit.ts`.
- Where a cast is truly unavoidable (e.g. `session-filters.ts:8` `return el as T`),
  add the Rust-style `// SAFETY:` comment the standard requires.

Effort: medium, mechanical, well-bounded; do it after #1 so the linter guards it.

### 3. Extract pure logic into tested, named functions (medium, high test value)

Several pure functions are reusable and the obvious home for the `fast-check`
property tests the standard wants, but they are trapped in closures and
untested: `normalizeText` (`session-filters.ts:64-69`), `formatBytes`
(`encounter-form.ts:26-30`), `parsePreferredSlots` (`timetable.ts:41-56`),
`toLocalDatetimeValue` (`encounter-form.ts:12-14`).

- Lift them into precisely named modules (e.g. `text-normalize.ts`,
  `format-bytes.ts`) imported by the entrypoints — consistent with the existing
  one-concept-per-file naming and with standard 14 (functional core).
- Add unit/property tests (roundtrip/idempotence for `normalizeText`,
  monotonicity/bounds for `formatBytes`). This also exercises the otherwise
  unused testing-pyramid layers the standard prioritizes.

Effort: medium; pairs naturally with #2.

### 4. Tagged errors and a tiny `prelude.ts` (small, lower priority)

Standards 3 and 4 want tagged errors and shared `casesHandled` /
`shouldNeverHappen` helpers. At this size the payoff is modest, but a small
`prelude.ts` with `shouldNeverHappen(msg)` and a tagged `DomError` would let the
bare `throw new Error(...)` sites (`modal.ts:93`, `session-filters.ts:7,16`)
carry a stable tag and context, and give exhaustive-union dispatch a home if the
TS surface grows.

Effort: small. Defer unless the TS surface expands.

### 5. JSDoc on exported symbols (quick win, mechanical)

Standard 28 asks for JSDoc on every export. The only runtime exports are
`openModal`/`closeModal` (`modal.ts:365`); document them with `@param`/`@returns`.
The codebase already documents *why* well (standard 29 ✅); this is just adding
the per-symbol `@param` form on the handful of public entry points.

Effort: trivial.

### Explicitly out of scope / not worth chasing

Errors-as-values plumbing, `Result`/Effect, branded domain types, schema
libraries, adapter/repository patterns, DI, sagas/idempotency, `Clock`/`Random`
injection — these solve problems this thin DOM layer does not have. Forcing them
in would add ceremony without correctness gains and would contradict the
standard's own rule 4 ("avoid broad migrations unless explicitly requested") and
decision-priority #2 ("follow established project architecture"). Revisit only
if real domain logic ever moves into TypeScript.

## Bottom line

The TypeScript here is a small, well-commented, single-convention
progressive-enhancement layer. Against the standard it scores well on module
design, naming, imports, comments, and boolean-blindness avoidance; it is weakest
on the safety toggles that are cheap to fix: missing strict `tsconfig` flags, no
linter enforcing them, pervasive `!`/`as` without SAFETY comments, and no unit
tests for the pure helpers. The high-value path is enforcement (#1) plus the
mechanical cast/assertion cleanup (#2) — not a domain-modeling rewrite.
