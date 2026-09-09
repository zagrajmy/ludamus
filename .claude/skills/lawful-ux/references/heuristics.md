# Heuristics — how people perceive, decide, and remember

Each entry: **claim → origin → the number, if there is one → what it obligates
→ the smell**. Read the entry before citing it; the numbers are the part
people misquote.

## Hick's Law

Decision time grows logarithmically with the number of equally likely choices.

- Origin: William Edmund Hick (1952), Ray Hyman (1953).
- Number: `RT = a + b·log₂(n + 1)`. The log matters: going 2 → 4 options costs
  about as much as 4 → 8. There is no magic maximum, but 3–5 top-level choices
  is where most navigation stays scannable.
- Obligates: prioritize before you list. Break long option sets into stages
  (progressive disclosure), highlight the recommended default, and never make
  the user choose what you could decide for them.
- Caveats: it assumes options are equally likely and comprehensible. Ten
  obvious items can be faster than four cryptic ones — grouping and labeling
  can beat deletion. Cutting options users need is not a Hick fix, it's a
  feature cut.
- Smell: a settings screen where every option is a top-level radio; a form
  showing a select with one selectable value; six filters given equal weight
  when one is used 90% of the time.

## Fitts's Law

Time to acquire a target is a function of distance to it and its size.

- Origin: Paul Fitts (1954).
- Number: `T = a + b·log₂(2D / W)`. Practical floors: ≥24 px hit target for
  pointer input, ≥44 px for touch, with spacing between adjacent targets so a
  mis-hit isn't destructive.
- Obligates: make the primary action big and near where the eye and hand
  already are. Put a control next to what it acts on. Exploit "infinite" edges
  and corners — a target flush against a screen edge is effectively
  unmissable, which is why mobile bottom bars work.
- Smell: a 14 px icon glyph as the only delete affordance; primary CTA the same
  size as three secondaries; a destructive action adjacent to the common one
  with no gap.

## Doherty Threshold

Productivity soars when the system and the user respond to each other faster
than 400 ms — neither waits on the other.

- Origin: Walter J. Doherty and Ahrvind J. Thadani, IBM (1982).
- Number: 400 ms. Related perceptual bands: <100 ms feels instant, ~1 s keeps
  the flow of thought, >10 s loses attention entirely (Nielsen).
- Obligates: acknowledge input immediately even when the work isn't done —
  optimistic UI, skeletons that match the coming layout, progress that moves.
  Perceived speed is designable independently of real speed.
- Caveats: it cuts both ways. Some operations (deleting an account, submitting
  a payment) benefit from a deliberate pause that reads as diligence.
- Smell: a button that looks unclicked for 800 ms; a spinner replacing the
  button label so the user loses what they pressed; a page that shows nothing
  until every query returns.

## Jakob's Law

Users spend most of their time on *other* sites, so they expect yours to work
like the ones they already know.

- Origin: Jakob Nielsen.
- Obligates: honor convention for anything the user did not come here to learn
  — login, navigation, forms, tables, dates, cart-like flows. Spend novelty
  where the product is actually different. When you must change a familiar
  pattern, let people use the old way for a while.
- Smell: a bespoke date picker; a "clever" nav that hides the primary action;
  a redesign justified by freshness that resets everyone's muscle memory.

## Miller's Law

The average person can keep about seven (±2) items in working memory.

- Origin: George A. Miller (1956).
- Number: 7±2 is about *digit span in immediate recall*, not about menu length
  — the most abused figure in design. Later work (Cowan, 2001) puts practical
  working memory nearer 4±1 chunks. Design to 4, not 7.
- Obligates: chunk. Phone numbers, codes, IDs, and long numbers get grouped;
  content gets headings and short paragraphs; steps get named stages. Chunking
  is the actionable half of this law — see below.
- Smell: an unformatted 16-digit reference; a wall of 12 sibling fields with no
  grouping; a wizard whose steps have no names.

## Chunking

People absorb and recall information faster when it is grouped into meaningful
units.

- Obligates: group by meaning, not by fitting the grid. Give each chunk a
  visible boundary (heading, card, region) and a name. Chunk time and dates,
  identifiers, and long forms into labeled sections.
- Smell: a form section titled "Other"; a table with 14 columns and no column
  groups; run-on card content with no internal hierarchy.

## Tesler's Law (Conservation of Complexity)

Every system has an irreducible complexity; the only question is who absorbs
it — the user, the interface, or the engineering.

- Origin: Larry Tesler, at Xerox PARC.
- Obligates: when "simplifying", say where the complexity went. Absorb it in
  the system (smart defaults, inference, validation that fixes rather than
  scolds) rather than pushing it into the user's head or into a doc. Don't
  oversimplify to the point that experts must build workarounds.
- Smell: a UI that "just" asks the user to compute a value we could compute; a
  removed field that becomes a support email; a wizard that collects less and
  is followed by a correction step.

## Postel's Law (Robustness Principle)

Be liberal in what you accept, conservative in what you send.

- Origin: Jon Postel (1980), RFC 760/793, borrowed into interface design.
- Obligates: accept input in whatever shape a human produced — spaces in card
  and phone numbers, mixed case, trailing whitespace, dates in the local
  order, pasted values — and normalize it silently. Anticipate variance in
  input methods, connection quality, and accessibility needs. Then output
  something predictable and well-formed.
- Caveats: liberal parsing must not become liberal *interpretation* of intent:
  never guess when guessing wrong is destructive, and never accept invalid data
  into storage. Ambiguity gets a confirmation, not a coin flip.
- Smell: "invalid phone number" for `+48 123 456 789`; an email field that
  rejects a trailing space; a form that clears itself on a validation error.

## Goal-Gradient Effect

Motivation increases as people approach a goal — the closer the finish, the
faster they move.

- Origin: Clark Hull (1932); the coffee-card study is Kivetz, Urminsky and
  Zheng (2006), where cards with two "free" stamps pre-filled were completed
  faster than shorter cards starting at zero.
- Obligates: show progress, and show it as *nearly done* where honest —
  endowed progress ("2 of 5 done" including what we already know) beats an
  empty bar. Make the remaining work look finite: named steps, a real count.
- Caveats: fake progress is a lie with a short half-life. Only endow progress
  for work genuinely already complete.
- Smell: a multi-step flow with no step indicator; a profile that says
  "incomplete" without saying what's missing or how much is left.

## Zeigarnik Effect

People remember interrupted or unfinished tasks better than completed ones —
an open loop stays open in the mind.

- Origin: Bluma Zeigarnik (1927).
- Obligates: make unfinished work visible and resumable — drafts, saved state,
  "continue where you left off", a badge on the incomplete thing. Use it to
  help people return, not to nag.
- Smell: an abandoned form that loses everything on navigation; a half-finished
  submission with no trace anywhere in the UI.

## Peak-End Rule

People judge an experience largely by its most intense moment and its end, not
by the average of every moment.

- Origin: Daniel Kahneman and colleagues (1993 onward).
- Obligates: find the peak (usually the hardest or most emotional moment) and
  the end (confirmation, completion, error, cancellation) and design those
  hardest. A gracious failure state is worth more than five polished neutral
  screens.
- Smell: a beautiful flow that ends in a bare "OK"; an error page written by
  the framework; a cancellation path nobody has read since it was written.

## Serial Position Effect

Users remember the first and last items in a series best; the middle blurs.

- Origin: Hermann Ebbinghaus (primacy and recency).
- Obligates: put the most important items first and last. In navigation, the
  edges carry the load; in a list of actions, don't bury the one that matters
  in the middle.
- Smell: the primary action third of five in a toolbar; the key column in the
  middle of a wide table.

## Von Restorff Effect (Isolation Effect)

When several similar objects are present, the one that differs is the one
remembered.

- Origin: Hedwig von Restorff (1933).
- Obligates: exactly one thing per view should be visually loudest, and it
  should be the thing the user came to do. Emphasis is a budget — spending it
  twice spends it nowhere.
- Caveats: never carry meaning by color alone (color blindness, dark mode,
  grayscale printing), and don't let emphasis mimic an ad — banner blindness is
  real.
- Smell: three primary buttons on one screen; every card with a colored badge;
  a "New" pill on nine of ten rows.

## Selective Attention

People filter out what they judge irrelevant, often missing it entirely.

- Obligates: keep critical information out of ad-shaped slots (right rail,
  banner strips, anything that looks promotional), and place it in the path of
  the task instead. Errors and consequences belong next to the control that
  caused them.
- Smell: a validation summary at the top of a long form; a critical notice in a
  dismissible banner styled like marketing.

## Aesthetic-Usability Effect

People perceive attractive designs as more usable, and are more tolerant of
minor problems in them.

- Origin: Masaaki Kurosu and Kaori Kashimura (1995), Hitachi ATM study.
- Obligates: visual quality is not decoration — it buys trust and forgiveness.
  It also *masks* usability problems in testing, so don't read "they liked it"
  as "they could use it". Watch what people did, not what they said.
- Smell: a usability test where every issue is explained away; a polished
  surface over a flow nobody completed.

## Paradox of the Active User

Users never read the manual; they start doing immediately, and stay stuck in
suboptimal habits.

- Origin: John M. Carroll and Mary Beth Rosson (1987).
- Obligates: teach in the flow, not in a doc — sensible empty states, inline
  hints at the moment of need, defaults that are already correct. Assume the
  onboarding modal was dismissed.
- Smell: a feature whose discoverability plan is a help page; a first-run tour
  that must be completed to understand the screen.

## Parkinson's Law

Work expands to fill the time available for its completion.

- Origin: Cyril Northcote Parkinson (1955).
- Obligates: shorten the task and people finish faster — autofill, remembered
  values, sane defaults, fewer required fields. Bounded time (a visible
  deadline, a hold timer on a seat) concentrates action, when honest.
- Smell: a checkout that re-asks for known data; an enrolment form asking for
  what the profile already holds.

## Flow

Deep engagement comes from a task whose challenge matches the user's skill,
with clear goals and immediate feedback.

- Origin: Mihály Csíkszentmihályi.
- Obligates: don't interrupt a working user with anything that can wait —
  modals, tours, surveys, upsells. Keep feedback tight (see Doherty) and state
  visible so returning is cheap.
- Smell: a rating prompt mid-task; a session that expires silently while the
  user is typing.

## Working memory and cognitive load

Working memory is small and short-lived; total load is intrinsic (the task) +
extraneous (how we present it).

- Origin: Baddeley and Hitch (1974); cognitive load theory, John Sweller (1988).
- Obligates: cut extraneous load — that's the part design controls. Keep
  needed information on screen instead of asking the user to remember it
  across steps; prefer recognition over recall; don't split related content
  across a scroll or a step boundary.
- Smell: a confirmation step that doesn't show what was chosen; a code sent by
  email that the form won't let you paste; a summary that omits the values it
  is summarizing.
