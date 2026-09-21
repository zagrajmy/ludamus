# Proposal wizard

The wizard is how a facilitator offers a session: category, personal data,
time slots, details, review, submit. It is a public, multi-step form on the
event.

## Sub-features

- `propose-open` opens the wizard from the event page.
- `propose-category` chooses a kind of session.
- `propose-continue` walks the remaining steps to review.
- `propose-submit` creates the proposal.

## How to get to it (user POV)

- On `/event/autumn-open/` choose `Propose a session`
  (proposals must be open on that event).
- Direct: `/event/autumn-open/session/propose/`.

## Driving it with control-ludamus

Preconditions:

- `autumn-open` exists and has proposals open (`proposal_start_time` /
  `proposal_end_time` cover now. Bootstrap sets this).
- Anonymous is allowed on that event when seed says so. Otherwise sign in.
- Pick a title that is not already in the programme so cleanup can find it.

- **Open.** Run
  `mise run control-ludamus -- open /event/autumn-open/` then
  `mise run control-ludamus -- find role link click --name "Propose a session"`.
  Or `open /event/autumn-open/session/propose/`. Heading
  `What would you like to propose?` is visible. `#wizard-content` is the step.
- **Category.** Choose a radio card (the category name is visible text) and
  `Continue`. Run
  `mise run control-ludamus -- find role button click --name Continue`
  after selecting a category. The next step replaces `#wizard-content`.
- **Walk the steps.** Personal data, then time slots, then details, then
  review. Each step posts into `#wizard-content`. Back controls return to the
  previous step without losing entered values.
- **Submit.** On review, submit. A success state names the new proposal.
- **Proof.** Snapshot of review before submit, snapshot/screenshot after.
  Reopen the event or panel proposals list and find the title. MCP
  `list_sessions --event autumn-open` may corroborate. Creating via
  `create_session` is not this feature.

## Gotchas

- A single remaining category must not become a pointless extra click if the
  UI already collapses it (`render_forced_choice`). If only one category
  exists, the first step may already be chosen.
- Login nudge on personal data is not a hard wall when anonymous proposals
  are on.
- Do not assert markup of the stepper. Assert the heading and that Continue
  advances.
- Rate limiting is by IP in the service. Do not hammer submit in a loop.
