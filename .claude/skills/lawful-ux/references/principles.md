# Principles — where to spend design effort

The laws in [heuristics.md](heuristics.md) describe people. These describe
work: what to build, what to cut, and how much to invest.

## Occam's Razor

Among competing designs that predict the same outcome, choose the one with the
fewest assumptions — and keep removing elements until the design breaks.

- Origin: William of Ockham (14th century), as a rule for explanations; adopted
  into design as a rule for elements.
- Obligates: analyze each element, then remove it and look. If nothing is lost,
  it stays out. Test the reduced version against the real job, not against
  taste — "clean" that costs a user their task is not simpler, it's worse (see
  Tesler's Law).
- Method: strip to the minimum that does the job, then add back only what a
  reachable state or a real user need demands.
- Smell: a divider between two things already separated by 32 px of air; a
  count badge next to a list that shows its own count; a subtitle restating the
  title.

## Pareto Principle

Roughly 80% of effects come from 20% of causes.

- Origin: Vilfredo Pareto (1896), land-ownership distribution.
- Obligates: find the small set of features and paths that carry most of the
  use, and spend the effort there — polish, speed, and error handling included.
  The long tail should work correctly; it does not need equal investment.
- Caveats: it is an observation about distributions, not a licence to ignore
  the tail. Accessibility, correctness, and data safety are not tail features
  even when the path is rare.
- Smell: a redesign that repaints the rarely-used admin screen while the
  primary flow keeps its 2019 form; an audit whose findings are all cosmetic
  and none about the top path.

## Hierarchy of investment (how these combine)

When time is finite, this is the order that survives contact with users:

1. **The top path works and is fast** (Pareto + Doherty).
2. **Its peak and its end are designed** (Peak-End) — including the failure.
3. **The grouping is unambiguous** (Gestalt) and one thing is the figure
   (Von Restorff).
4. **Choices are few and defaulted** (Hick), with complexity absorbed by the
   system (Tesler).
5. **Then** the long tail, the decoration, and the novelty.

Anything proposed out of that order needs a reason stated in the PR.
