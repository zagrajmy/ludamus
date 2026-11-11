---
version: 1
slug: "src-ludamus-client-src-parley-parley-tsx"
primary_target: "src/ludamus/client/src/parley/parley.tsx"
related_targets: ["src/ludamus/client/src/parley/conversation.tsx","src/ludamus/client/src/parley/message-item.tsx"]
---

# Parley chat window

Scope: Parley's client UI (launcher, room list, conversation). Visitor mode:
Operate.

Audience: participants, programme creators and organisers of one sphere, on
phones at the venue and on laptops before an event. Job: read and answer a
sphere-wide or session room quickly, without leaving the page they are on.
Constraints: Tessera tokens (Outfit, coral primary, warm neutrals, light and
dark), Polish copy from Django, keyboard reachable, existing Worker protocol.

Decisions (user, 2026-10-27): one docked window on desktop; the room list lives
in a launcher popover; per-bubble ⋯ menu carries copy link, report, delete,
moderator delete and mute.

## Direction contract

THESIS: Parley is a Messenger-style chat window docked to the page corner, not a
modal panel. It refuses the backdrop-and-two-column admin panel the first build
shipped.

OWN-WORLD: Zagrajmy's own palette — own bubbles in coral primary with white
text, others' bubbles on the warm tertiary ground, warm hairline borders, Outfit
throughout, heroicons mini in one weight, the app's initials avatars
(coral/teal/warm by name). Rounded-2xl bubbles whose joined corners tighten
inside a run.

STORY: The visitor sees an unread badge on the chat button, opens the list,
picks a room, reads the run of bubbles, answers from the pill composer, and acts
on a message from its ⋯ menu.

FIRST VIEWPORT: Desktop: 380×560 window docked bottom-right above a 56px coral
chat button; header with room avatar, title and live presence line, back-to-list
and close; bubbles fill the body; pill composer with send icon at the foot.
Mobile: the same window full-screen.

FORM: Messenger chat window, pinned by the user's own words — "It should look
like a chat window like Facebook Messenger" — so the concept roll was skipped as
a precisely specified form and no seed key exists; code-led.

FINISH: unreviewed and undocumented is unfinished; this build ends with the
finish review, the verdict, DESIGN.md, and every shipping raster carrying its
provenance
