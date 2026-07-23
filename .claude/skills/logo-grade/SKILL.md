---
name: logo-grade
description:
  Grade, lint, and evaluate logos against a research-backed rubric (Rand,
  Haviv, Bass, Leader + neuro-design principles). Use whenever the user asks
  to rate, grade, score, review, compare, lint, or pick between logo
  candidates, marks, wordmarks, favicons, or brand icons — including
  AI-generated logo sheets, SVG marks in docs/branding/assets, and "which of
  these is better?" questions about any logo image. Also use before shipping
  any new logo asset (navbar SVG, favicon, og:image) to verify it passes the
  hard gates.
---

# Logo grading and linting

Grade a logo the way the identity masters and the neuroscience both say it
should be judged: mechanics first (does it survive?), perception second
(does it read?), meaning last (does it say the right thing?). Output a
report card with a score out of 100, hard-gate verdicts, and prescriptions.

Never grade from a single large render. Most logo failures are invisible at
256 px and fatal at 16 px — the pipeline exists to surface exactly those.

## Pipeline

### Stage 1 — mechanical lint (SVG input)

Run `scripts/logo_lint.py <file.svg>`. It emits JSON findings:

- gradients / filters / blur / drop-shadow usage (gradient dependence is a
  structural failure: dies in one-color print, embroidery, favicons)
- unoutlined `<text>` elements (font dependency — the file breaks on any
  machine without the font; wordmarks must ship as paths)
- embedded raster images inside the SVG
- color census (more than 3 inks flags simplicity risk; excludes white)
- contrast of each fill vs white and vs near-black (WCAG-style ratio; a
  white-logo variant needs ≥ 4.5:1 background separation)
- stroke-width variance (inconsistent stroke reads as unfinished)
- path node count (complexity proxy; also predicts vectorization quality)
- tiny features: any shape whose smaller dimension is under ~2.5% of the
  canvas will not survive 16 px

For raster input (PNG/JPEG), skip the lint and note "raster input — lint
unavailable, grade from renders only" in the report.

### Stage 2 — render matrix

Run `node scripts/render_logo_sheet.js <file> <out.png>`. It produces one sheet
with: 256 px reference · 48/32/16 px reductions · grayscale · forced
one-color silhouette · white-on-dark · 8 px blur ("squint" — approximates
pre-attentive/peripheral vision from the neuro-design research).

Requires Chromium at `/opt/pw-browsers/chromium` and `playwright-core`
resolvable from the script (`npm i playwright-core` in this `scripts/`
directory or any ancestor). If unavailable, render what you can with PIL and
say which cells are missing.

### Stage 3 — vision grading

Read the sheet with vision and score the rubric. Read
[references/rubric.md](references/rubric.md) for the per-axis anchors,
weights, and the neuro-design principles behind them before scoring.

Axes (weights sum to 100): simplicity/fluency 20 · reduction/adaptability
20 · distinctiveness/saliency 15 · memorability/density 15 ·
appropriateness 10 · timelessness 10 · craft/geometry 10.

Score each axis from its anchor table, not from vibes. Cite what you see
in specific render cells as evidence ("at 16 px the seats merge into a
blob" — not "feels busy").

### Stage 4 — hard gates

Independent of the numeric score, the mark is **NOT SHIP-READY** if any of:

- illegible or ambiguous at 16 px
- one-color silhouette loses the idea
- white-on-dark version fails (halos, lost counters, < 4.5:1 contrast)
- gradient- or effect-dependent (lint)
- unoutlined text (lint)

A 90-point mark that fails a gate still fails. Say so plainly.

### Stage 5 — prescriptions

For each axis scoring below 70% of its weight, prescribe one concrete fix
in the voice of the relevant master (see rubric reference): Rand → reduce
shape count; Bass → add one point of tension; Leader → iterate the
letterforms, the idea is inside them; Bierut → empty the vessel, remove
preloaded symbolism; Draplin → thicken strokes, print at half an inch;
Scher → give the system one loud register.

## Report card format

Use this exact template (one per candidate):

    # Logo report: <name>
    **Verdict: SHIP-READY | NOT SHIP-READY | NEEDS WORK** · Score NN/100

    | Axis | Score | Evidence |
    |---|---|---|
    ...

    ## Hard gates
    - 16 px: pass/fail — <evidence>
    ...

    ## Lint findings
    ...

    ## Prescriptions
    1. ...

## Comparing candidates

When grading multiple marks, grade each independently first, then rank in
a single table. Do not let ranking pressure inflate individual scores —
per Haviv, it is normal for every candidate in a round to fail. Recommend
at most one primary direction plus one challenger; a menu of "all fine"
grades means the grading failed.

## Grading generated sheets

For AI-generated exploration grids (3x3 sheets etc.), grade cells
individually only after a cull pass: reject any cell with mushy edges,
accidental gradients, warped letterforms, or mismatched twin shapes
(known diffusion failure modes) before spending a full rubric pass.
Note that per the generation research, AI output is "an image of a logo" —
grade it as a concept study; production readiness requires the vector
rebuild.
