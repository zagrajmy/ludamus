# /tbd-card

Produce `.tbd/card.md` — a feature card that bridges the feature file
to implementation. This is the human review gate; nothing downstream
runs until the card is confirmed.

## Input

A feature file. If ambiguous, ask.

## What you do

1. Read the feature file.
2. Read the codebase enough to place the feature: what exists, what
   doesn't, where the edges are.
3. Write `.tbd/card.md` (see Shape below).
4. Show the card. Wait for confirmation before anything else runs.

## Shape

### Understanding

2–3 sentences. What the user/operator gains. What the core novelty
is. What this deliberately does not touch. Domain language only —
written for someone who knows the product but hasn't read the
feature file.

This is the section the human reads to verify your mental model is
correct. Get it wrong here and nothing downstream matters.

### New things

Concepts or entities that don't exist yet. One line each — named and
described in a clause. If there's nothing new, say so explicitly.

### Extends

What already exists that this feature grows or changes. One line per
thing. If nothing existing is touched, say so explicitly.

### The rule

The one load-bearing constraint or invariant. If you find two, the
feature should probably be two cards — flag it.

### Not now

Explicit deferrals. What the feature file implies but this delivery
doesn't cover. If nothing is deferred, omit this section.

## Vocabulary

Same discipline as the feature file: no file paths, no class names,
no function names, no framework nouns. Domain language and plain
English only.

If you'd write `EventIntegrationForm` or `views/integrations.py`,
you're in `/tbd-plan` territory. Save it.

## Length

Typical: 10–20 lines. If you're hitting 30, the feature is probably
two features — flag it and ask before continuing.

## Don'ts

- No DDD ceremony. No "Command —", "Policy —", "Read model —".
- No interaction surface walkthrough. The understanding and extends
  sections cover placement.
- No rationale or motivation prose.
- Don't proceed to plan until the user confirms the card.
