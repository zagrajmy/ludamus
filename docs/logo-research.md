# Zagrajmy logo research digest

Compiled 2026-07-22 from four parallel research passes: designer canon,
principles, niche landscape, and the AI-to-vector pipeline. It informed
the brand system that landed in
`src/ludamus/templates/components/brand/`.

## 1. Designers worth stealing from

Paul Rand (IBM, UPS, ABC): geometric clarity over decoration. Saul Bass
(AT&T bell, United tulip): kinetic minimalism, metaphor as thinking made
visible. Milton Glaser (I ❤ NY): decoration can be purposeful. Lindon
Leader (FedEx): the hidden arrow came out of 200+ typographic iterations,
not the brief. Michael Bierut (Mastercard, MIT Media Lab): typographic
restraint. Paula Scher (Citi, The Public Theater): boldness that feels
"unexpected and inevitably right". Sagi Haviv (US Open): process over
aesthetics. Aaron Draplin (Field Notes): sketch in pencil to exhaustion
before touching vectors.

Contemporary studios: Smith & Diction (Perplexity), Manual (Obama
Presidential Center), Koto (Gumtree, Glassdoor), Order (Herman Miller,
logos as extensible systems), DIA (kinetic identities).

## 2. Principles and tests

Rand: "A logo derives meaning from the quality of the thing it symbolizes,
not the other way around." His 7-step test scores simplicity 1 to 15 while
everything else gets 1 to 10. Reduction is the heaviest discipline.

Haviv: a trademark must be appropriate, distinctive, and simple. It should
not carry the whole brand story. Bierut agrees from the other side: a new
logo is "an empty vessel awaiting the meaning that will be poured into it
by history and experience", so preloaded symbolism inhibits what the mark
can become. Leader: "Simplicity and clarity. Great design is born of those
two things." Bass pushed abstraction "to its utmost limits, yet still
readable"; simple-simple is boring. Draplin: show thick and thin, and make
something that belongs to the client, not the designer.

The modern consensus tests:

1. Reduction: legible from a 16 px favicon to a billboard.
2. One color: must work in solid black and reversed white before the
   palette is trusted. Gradient dependence is a structural liability.
3. Mark type: new brands start with a wordmark or combination mark;
   symbol-only is the payoff of accrued equity, not a starting point.
4. Concept count: the CG&H school presents very few concepts, often one,
   applied across real touchpoints instead of an icon in isolation.
5. Construction: grid first, then optical correction. The math says one
   thing, the eye says another, and the eye wins. Responsive systems ship
   3 to 4 tiers (lockup, mark, glyph, favicon), each redrawn on purpose.

## 3. Niche landscape (tabletop + events)

The field splits into two poles with an empty middle: corporate-serious
(Roll20's black wordmark, Gen Con's no-effects brand rules, PAX) versus
chaotic-fun (Partiful's sticker maximalism, clip-art dice clusters).
"Warm, confident, approachable" is unclaimed. Meetup and Eventbrite own
orange; Luma owns neon purple. Restraint plus one accent stands out.

Cliché blacklist, invisible from overuse: meeples, d20s, dice pips, pawns,
cards, dominoes, speech bubbles, neon gradient auras.

The opportunity: geometric abstraction derived from what the product
actually does (tables, seats, schedule grids), Polish poster-school
geometry, and a mark that performs at favicon scale. Pyrkon, Copernicon,
and Falkon don't compete on visual identity.

## 4. AI generation to vector pipeline

| Model | Strength | Weakness |
| --- | --- | --- |
| Ideogram v3 | best legible in-image text | |
| Recraft V3 | native SVG, brand palettes | ecosystem lock |
| GPT-image | flat shapes, transparent bg | text below Ideogram |
| Qwen-Image | strongest text, open source | Western mark aesthetics |
| Midjourney | abstract symbols via `--sref` | worst text, over-renders |

Prompt pattern: stack qualifiers and name exact hexes.

    flat vector logo, [subject], minimalist, simple geometric shapes,
    solid colors, icon only, centered composition, white background,
    using only #f85a3c and #252220, no gradients, no 3D, no drop
    shadows, no photorealism, clean edges

Cull these failure modes: mushy edges, sneaky gradients and bevels,
garbled letterforms (diffusion learns pixels, not characters), and
structural inconsistency like mismatched radii or asymmetric twins.

Vectorize with Vectorizer.ai (cleanest few-node output), Recraft's
built-in tracer, Illustrator Image Trace, or Inkscape with potrace. The
rule: AI output is *an image of a logo*. Rebuild the wordmark in real type
(Outfit) and correct nodes by hand.

## Sources

All accessed 2026-07-22; model comparisons and landscape claims reflect
that date.

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
