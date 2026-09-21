# Gestalt principles — how the eye groups things

Perception organizes a screen before anyone reads it. Gestalt psychology
(Wertheimer, Köhler, Koffka, 1920s) describes that organization. In interface
work these are the cheapest tools available: they change meaning by changing
space, not markup.

The order of strength, when they compete: **common region > proximity >
similarity**. A border wins over whitespace; whitespace wins over matching
color. Use the strongest one the layout needs, and only that one — a card with
a border, a background, a gap, *and* a divider says the same thing four times.

## Law of Proximity

Objects near each other are perceived as a group.

- Obligates: whitespace is the grouping mechanism. The gap *inside* a group
  must be visibly smaller than the gap *between* groups — if they're equal,
  the grouping doesn't exist no matter what the labels say.
- Obligates: put a label nearer its own field than to the next field, and an
  action nearer the thing it acts on.
- Smell: uniform spacing down a form; a helper text equidistant between two
  inputs; a section heading with as much air below it as above.

## Law of Common Region

Elements inside a shared boundary are perceived as a group — a border or a
background beats mere proximity.

- Obligates: use a container (card, panel, bordered region) when you need a
  grouping that survives being far apart or being interleaved with other
  content. Removing a container merges its contents into whatever is around it.
- Caveats: containers are expensive ink. Nested cards inside cards inside
  panels flatten hierarchy instead of building it — one boundary per level.
- Smell: a card whose contents belong to two different things; a "group" that
  is only a heading and hope.

## Law of Similarity

Elements that share visual characteristics — color, shape, size, orientation —
are perceived as related, and as having the same function.

- Obligates: same look means same behavior. Links look like links, buttons
  look like buttons, and anything that looks like either must be clickable.
  Conversely, two controls with different consequences must not look identical.
- Smell: colored non-interactive text; a destructive action styled like the
  neutral ones; badges that look like buttons.

## Law of Prägnanz (good figure, simplicity)

People perceive ambiguous or complex images in the simplest form possible,
because it takes the least cognitive effort.

- Obligates: prefer the simplest arrangement that carries the meaning — a
  regular grid over a bespoke ragged one, few alignment lines, few shapes,
  fewer decorative strokes. Complexity that is not carrying information is
  being decoded for nothing.
- Smell: a layout with five different column widths; icons that need a legend;
  ornamentation that competes with content for the eye.

## Law of Uniform Connectedness

Elements that are visually connected — by a line, a frame, a shared background,
a continuous shape — are perceived as more related than elements with no
connection, even than nearby ones.

- Obligates: use an explicit connector when the relationship must survive
  reflow. Grouping created only by proximity breaks the moment content wraps to
  a narrow viewport or a longer translation pushes items to new rows; a shared
  background or an enclosing element does not.
- Smell: a row of related tokens that becomes two ragged rows on mobile and
  loses its grouping; a "toolbar" that is only three buttons that happen to sit
  side by side.

## Law of Closure and continuity (the rest of the family)

The eye completes partial shapes and follows continuous paths.

- Obligates: a truncated row or a cut-off card *is* a legitimate scroll
  affordance — a peeking edge says "more this way" better than an arrow. Keep
  paths continuous: aligned edges read as a line to follow, broken alignment
  reads as a new thing.
- Smell: a horizontally scrollable list whose last visible item ends exactly at
  the viewport edge, so nothing suggests there's more.

## Figure/Ground

The eye separates a scene into a subject and a background.

- Obligates: one figure per view. Elevation, contrast, and blur/scrim decide
  what is the subject — a modal works because its scrim demotes everything
  else. If everything is elevated, nothing is figure.
- Smell: shadows on every card so the page reads as a field of equals; a dialog
  without a scrim; an "active" state indistinguishable from ambient decoration.

## Applying them in review

Ask, in this order, of any grouping on the screen:

1. Do the gaps say what the headings say? (proximity)
2. Does anything that looks alike behave differently? (similarity)
3. Does the grouping survive a rewrap and a 20%-longer Polish string?
   (uniform connectedness)
4. Is there exactly one figure? (figure/ground, Von Restorff)
5. Is any of this grouping being stated more than once? (Prägnanz — remove the
   weakest signal, not the strongest)
