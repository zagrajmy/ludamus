# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

The primary users are organizers of Polish game conventions and smaller game
meetups (tabletop, RPG, LARP), and the participants who join their sessions.
Organizers publish a programme; participants sign up for sessions, often as a
group.

Around them: program creators propose sessions, event managers run an event
inside a sphere-scoped backoffice (the Panel), and sphere teams configure their
events without receiving global Zagrajmy staff access.

## Product Purpose

Ludamus helps communities run events and smaller game meetups. It succeeds when
organizers can publish a dependable program, participants can understand and
manage their attendance, and each sphere team can operate independently within
its authorization boundary.

## Positioning

Three differences are deliberate and true of Ludamus:

- **Fair session sign-ups.** Seats, waitlists and group sign-ups cannot
  double-book a person or overbook a session.
- **Each community runs itself.** Every community (a "sphere") has its own
  space, Panel and team, and routine event work does not depend on the
  Zagrajmy staff.
- **Proposal to programme.** One flow takes sessions from proposal through
  scheduling to a published programme.

## Operating Context

- Organizers work in the sphere-scoped Panel: event settings, proposals,
  scheduling into spaces and time slots, enrollment, and ticket types.
- Participants browse the programme, enroll alone or with their party, and
  manage their attendance.
- Ticket sales connect through Stripe.
- Maintainers also operate events through an MCP server (`/mcp/`).

## Capabilities and Constraints

- Copy is English and Polish; every user-facing string is translatable.
- UI is built from the Tessera component system and Tailwind tokens in
  `src/ludamus/client/src/index.css`, with light and dark themes.
- Request-supplied ids are scoped to the current sphere and event; Panel access
  never implies global staff access.

## Brand Commitments

Respectful, straightforward, and dependable. The interface should feel friendly
to hobby communities without sacrificing the clarity expected from operational
software.

Avoid generic SaaS decoration, configuration hidden behind global
administration, and clever controls that obscure standard form behavior.

## Evidence on Hand

The landing pages (`src/ludamus/templates/landing/`) carry existing copy,
including organizer testimonials. Do not invent further testimonials, customer
names, attendance numbers or pricing.

## Product Principles

- Keep sphere work inside the sphere-scoped Panel.
- Respect users' time with strong defaults and direct workflows.
- Use familiar controls and the existing Tessera component vocabulary.
- Explain consequences where settings affect participants or capacity.
- Preserve clear authorization boundaries between sphere teams and global staff.

## Accessibility & Inclusion

Use semantic HTML, labeled controls, keyboard-operable interactions, visible
focus states, sufficient contrast, reduced-motion support, responsive layouts,
and translatable English and Polish copy.
