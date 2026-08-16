# Facilitator fields need their own configuration

## Where we are

Personal-data fields hang off the event (`PersonalDataField.event`), and
`PersonalDataFieldRequirement` says which of them a proposal category asks for
and whether the answer is mandatory. That is the only configuration there is.

The facilitator-facing pages don't use it. `_personal_fields_form` in
`chronology/panel/views/facilitators.py` calls
`personal_data_fields.list_by_event` and pairs every field with
`is_required=False`, with the comment that the panel records answers on
someone's behalf. The proposal form's per-facilitator blocks
(`_facilitator_fields_form` in `panel/views/proposals.py`) do the same.

So an organizer configuring an event has one lever — "this category asks for
diet" — and it reaches only the proposal wizard. Every personal-data field on
the event shows up on the facilitator create and edit pages whether or not it
has anything to do with a facilitator record, and none of them can be made
mandatory there.

## What's wrong because of it

**Every field, every facilitator page.** An event that collects a wizard-only
answer (a t-shirt size for attendees, say) puts that question on the organizer's
facilitator form too, because "all event fields" is the only list available.

**Nothing can be required of a facilitator.** The `is_required=False` is
hardcoded, not configured. An organizer who genuinely needs a phone number for
every facilitator has no way to say so.

**Writes are scoped wider than reads.** `_personal_data_forms` intersects the
posted `personal_data_facilitator_ids` with
`facilitators.list_by_event(event_pk)`, while the render path builds blocks from
`sessions.read_facilitators(proposal_id)`. A stale or crafted POST therefore
writes answers for a facilitator whose block the page never rendered. It is not
a privilege escalation — the values are keyed `(facilitator, event)` and the
same organizer can edit them on the facilitator page — but the write accepts
input the form never offered.

The obvious one-line fix (scope to `read_facilitators(proposal_id)`) is wrong:
`ProposalFormPageView.post` serves create as well as edit, and on create there
is no proposal to read facilitators from. The correct scope is the facilitator
set selected in the same POST, which is a different set on each path — a sign
the scoping question belongs to a configuration model that doesn't exist yet.

## Shape of the fix

Give a personal-data field two independent switches instead of one:

1. **Facilitator config, per event** — does this field belong on a facilitator
   record, and is it required there? A new requirement row hanging off the event
   rather than off a proposal category, read by both facilitator pages and the
   proposal form's per-facilitator blocks.
2. **Category config, per proposal category** — unchanged: what the proposal
   wizard asks a proposer, which is already `PersonalDataFieldRequirement`.

Both then flow through the existing `dynamic_fields_form` /
`field_descriptors` path, so nothing in the rendering or validation layer
changes — only which `(field, is_required)` pairs each page asks for.

With facilitator requirements modelled, the scoping fix follows: a page that
knows which facilitators it is configuring can scope the write to exactly that
set, on both the create and the edit path.

## Steps

Each step is reachable through the UI on its own.

1. Requirement model + migration for facilitator-level personal-data fields,
   defaulting to "every existing field applies, none required" so current
   behaviour is preserved exactly.
2. A CFP panel screen to toggle the two switches per field, reachable from the
   existing personal-data field list.
3. Facilitator create/edit pages read the facilitator requirements instead of
   `list_by_event`, and honour `is_required`.
4. The proposal form's per-facilitator blocks do the same, and scope their
   writes to the facilitators the request actually configures.

## Not in scope

Merging `PersonalDataField` and `SessionField` into one table. They already
share `OrganizerFieldDTO`; the tables stay separate because they hang off
different owners.
