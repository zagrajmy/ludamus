---
status: draft
updated: 2026-09-13
points: 8
depends: [02]
---

# Panel navigation for intake and session configuration

## Event settings

As an organiser, I want availability windows managed under event settings,
so that they sit next to the other windows that shape the event.

As an organiser, I want the tab that opens proposals called "call for
proposals", so that the name matches what organisers call it and what the
public page announces.

## Session configuration

As an organiser, I want one place for session kinds, personal-data
questions, and session questions, so that everything describing what a
session is lives together.

As an organiser, I want that place useful whether or not a call for
proposals is open, so that I can prepare kinds and questions before opening
anything.

As a Polish-speaking organiser, I want the new navigation in Polish with the
established vocabulary, so that "przedział czasowy" and "rodzaj atrakcji"
keep their meaning.

## Optional: tracks

As an organiser, I want tracks reachable from the same place, so that every
session attribute is configured together.

Tracks are session attributes with managers and spaces of their own. Moving
them adds a fourth tab and drops the "Tracks" entry from the schedule group
in the sidebar. Do it only if the section feels incomplete without it —
this story ships separately or not at all.

## What it touches

- Time-slot pages move under event settings: URL paths under
  `settings/availability/`, a tab in `_event_settings_tabs.html`,
  `active_nav="settings"`. Copy: "Availability windows" / "przedziały
  czasowe". MCP tool descriptions say availability.
- The existing "Proposals" tab keeps its content — the event's proposal
  dates, description and anonymity setting — and is renamed "Call for
  proposals" / "Nabór zgłoszeń". No new model hangs under it; what a call
  accepts arrives in 06 as a flag on the kind.
- Sidebar: the top-level "Call for Proposals" entry becomes "Session
  configuration" (`PanelNav` key `session-config`), tabs Kinds, Personal
  data fields, Session fields.
