# Zagrajmy logo research digest

Compiled 2026-07-22 from four parallel research passes (designer canon,
principles, niche landscape, AI→vector pipeline). Companion to
[`logo-pitch.html`](./logo-pitch.html).

## 1. Designer canon

### Legends

- **Paul Rand** (IBM, UPS, ABC) — "everything is design"; geometric clarity
  and symbolic depth over decoration.
- **Saul Bass** (AT&T bell, United tulip, film titles) — kinetic minimalism;
  metaphor as "thinking made visible".
- **Milton Glaser** (I ❤ NY, DC bullet) — proved decoration can be purposeful.
- **Lindon Leader** (FedEx, Hawaiian Airlines) — strategic symbolism; the
  hidden arrow emerged from 200+ typographic iterations, not the brief.
- **Michael Bierut** (Mastercard, MIT Media Lab) — typographic restraint;
  minimal wordmarks.
- **Paula Scher** (Citi, The Public Theater) — theatrical boldness that feels
  "unexpected and inevitably right".
- **Sagi Haviv** (US Open, Library of Congress) — process-driven; strategy
  over aesthetics.
- **Aaron Draplin** (Field Notes, DDC) — exhaustive pencil sketching before
  vectors; anti-precious pragmatism.

### Contemporary studios worth studying

Smith & Diction (Perplexity — conceptual typography), Manual (Obama
Presidential Center — restraint), Koto (Gumtree, Glassdoor — "maximal
minimalism"), Order (Herman Miller — logos as extensible systems), DIA
(kinetic/generative identities).

## 2. Principles and tests

- **Rand:** "A logo derives meaning from the quality of the thing it
  symbolizes, not the other way around." His 7-step test weights simplicity
  1–15 while everything else (distinctive, visible, adaptable, memorable,
  universal, timeless) gets 1–10 — reduction is the heaviest discipline.
- **Haviv:** a trademark must be **appropriate, distinctive/memorable, and
  simple**. A logo shouldn't carry the whole brand story.
- **Bierut:** a new logo is "an empty vessel awaiting the meaning that will be
  poured into it by history and experience"; the designer's job is to make the
  vessel the right shape. Preloaded symbolism inhibits what the mark can
  become.
- **Leader:** "Simplicity and clarity. Great design is born of those two
  things." Iterate type rigorously; strong ideas are discovered, not briefed.
- **Bass:** "Pushed to its utmost limits in terms of abstraction and
  ambiguity, yet still readable." Simple-simple is boring.
- **Draplin:** show thick and thin; make something that is the client's, not
  the designer's signature.

### Modern consensus tests

1. **Reduction:** legible from 16 px favicon to billboard; reads as a single
   clear element.
2. **One-color:** must work in solid black, reversed white, and one spot color
   before palette is trusted. Gradient dependence is a structural liability.
3. **Mark type:** new brands start with wordmark or combination mark (name
   legibility first); symbol-only is the payoff of accrued equity, not a
   starting point.
4. **Pitfalls:** trend-chasing, gradient dependence, overdetail.
5. **Concept count:** CG&H-school practice presents very few concepts (often
   one), applied across real touchpoints rather than "wowing" with an icon in
   isolation.
6. **Construction:** grid first, then optical correction — "the math says one
   thing, the eye says another, and the eye wins." Responsive systems ship
   3–4 tiers (full lockup → mark → glyph → favicon), each a deliberate
   redesign.

## 3. Niche landscape (tabletop + events)

- **Two poles, empty middle:** corporate-serious (Roll20 black wordmark,
  Gen Con's no-effects brand rules, PAX minimalism) vs chaotic-fun (Partiful's
  Studio Kaki sticker maximalism, clip-art dice clusters à la Tabletop
  Simulator). "Warm, confident, approachable" is unclaimed.
- **Color territory:** Meetup and Eventbrite own orange; Luma owns neon
  purple/pink. Restraint + one accent stands out.
- **Cliché blacklist (invisible from overuse):** meeples, d20s, dice pips,
  pawns, cards, dominoes, speech bubbles, neon gradient auras.
- **Trends:** adaptive/morphing identities (Eventbrite "The Path", Partiful
  shape library); flat design standard; name legibility prioritized over
  symbol distinctiveness in conventions.
- **Opportunity:** geometric abstraction derived from actual product mechanics
  (tables, seats, schedule grids); Polish poster-school geometry; a mark that
  performs at favicon/badge scale; personality anchored in communal invitation
  rather than generic "fun". Pyrkon/Copernicon/Falkon don't compete on visual
  identity.

## 4. AI generation → vector pipeline

### Model strengths

| Model | Strength | Weakness |
| --- | --- | --- |
| Ideogram v3 | best legible in-image text/wordmarks | — |
| Recraft V3 | native SVG output, brand styles with your palette | ecosystem lock |
| GPT-image (gpt-image-1) | good flat shapes, transparent bg, decent short text | text below Ideogram |
| Qwen-Image | strongest text rendering (incl. multi-language), open source | less cited for Western mark aesthetics |
| Midjourney | abstract symbol fidelity via `--sref` | worst text, over-renders detail |

### Prompt pattern

Stack qualifiers, name exact hexes:

    flat vector logo, [subject], minimalist, simple geometric shapes,
    solid colors, icon only, centered composition, white background,
    using only #f85a3c and #252220, no gradients, no 3D, no drop
    shadows, no photorealism, clean edges

### Failure modes to cull

Mushy/soft edges; sneaky gradients/bevels/textures; garbled or warped
letterforms (architectural — diffusion learns pixels, not characters);
structural inconsistency (mismatched radii, asymmetric "twin" shapes).

### Vectorization

Vectorizer.ai (cleanest few-node output for high-contrast marks), Recraft
built-in (fastest, same platform), Illustrator Image Trace (production
control, needs tuning), Inkscape+potrace (free, scriptable, more cleanup).

**Rule:** AI output is *an image of a logo*. Always rebuild the wordmark in
real type (Outfit) and correct nodes by hand.

## Sources

Principles: fortheinterested.com (Rand 7-step), printmag.com (CG&H
interview), logodesignlove.com (Bierut, Haviv, concept counts),
99percentinvisible.org (Bierut "Negative Space"), wadads.com /
inkbotdesign.com (Leader, FedEx), logomaker.com (Bass quotes), logogeek.uk
(Draplin, Haviv podcasts, optical corrections). Landscape: studiokaki.co
(Partiful), uxdesign.cc (Eventbrite "The Path"), gencon.com brand
resources, alexmcleandesign.com (PAX), pyrkon.pl, brandfetch.com,
99designs.com, spellbrand.com. Pipeline: openai.com (4o image generation),
superside.com & manypixels.co (logo prompts), toolchase.com (Recraft),
qwenlm.github.io (Qwen-Image), perfectvector.com & gitnux.org
(vectorizers), lefthd.com & corwindesign.com (AI logo failure modes),
inkbotdesign.com (grids, responsive logos), akrivi.studio (logo tiers).
