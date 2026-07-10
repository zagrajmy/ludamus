# Copy — microcopy and translation

Every visible string is part of the design and is bilingual. Two non-negotiables:
wrap it for translation, and use the project's terms.

## Mechanics

- **Always translatable.** User-facing strings go through `{% translate "…" %}`
  (or `{% blocktranslate %}` for interpolation), never a bare literal. The same
  applies to `aria-label`, `sr-only` text, button labels, and validation
  messages.
- **Keep the catalog fresh.** After changing strings, run
  `mise run messages-check` — CI fails on stale, fuzzy, or untranslated PL
  entries. Add the Polish translation; don't leave it `msgid`-only.

## Voice

- **Actions are Verb + Noun.** "Save changes", "Delete proposal", "Create event"
  — not "Submit", "OK", "Confirm". The label says what will happen, so the user
  can act without reading surrounding text.
- **Errors point forward.** State what happened and what to do next, in plain
  language. No "An error occurred." with no exit. No blame ("You entered an
  invalid value") — describe the fix ("Enter a date in the future").
- **Don't shout the obvious.** If the page already says it, the button/help text
  doesn't need to repeat it. Redundant copy is the "redundant info" defect from
  CLAUDE.md.
- **Empty states invite.** "No proposals yet — create the first one" beats "No
  results."

## Polish term table (authoritative — from CLAUDE.md)

Use these consistently; they were chosen to avoid collisions. Getting them wrong
is a real translation bug, not a nuance.

| English | Polish | Note |
| --- | --- | --- |
| session | **punkt programu** | except "RPG session" → **sesja RPG** |
| track | **blok** / **blok programowy** | |
| facilitator | **twórca programu** | |
| time slot | **przedział czasowy** | do **not** use "blok czasowy" — collides with *track* |

When you introduce a new domain term, add it here (and to CLAUDE.md if it's
load-bearing) so the next agent translates it the same way.
