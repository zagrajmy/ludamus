---
status: done
updated: 2026-07-13
---

# Player shadowban

A personal, quiet safety tool: a player bans another player from their own
sessions without the banned person ever finding out. Escalation path: for
people who are unsafe event-wide, organizers use the hard event ban instead
(fake-full applied to the whole event).

## Pretend-full, never hidden (intended behaviour)

As a player, I want my sessions to look full to people I shadowbanned, so
that they cannot join and cannot tell they were banned.

- Sessions run by the banner render to the banned viewer as full, with
  simulacra participants and no way to enroll — exactly like the event-ban
  fake-full card.
- Direct enrollment links bounce back to the event page with no error
  message; the session simply looks full there.
- **Hiding the sessions instead is wrong and must not come back.** A hidden
  session is observable: the banned player can compare the program with a
  friend's view (or a logged-out tab) and infer who banned them, which is
  exactly the retaliation risk shadowban exists to avoid. A full session is
  deniable — the banner can say other players took the seats or cancelled.
  History: shadowban briefly shipped with hiding (`2b234c23`, PR #376);
  that was a mistake, corrected here.
- The banned player is never told in any flow: batch enrollment by a party
  manager skips them with a neutral "(not available)" reason.

## Warnings to the banner

As a player who shadowbanned someone, I want to hear when they show up
around me, so that I can decide what to do before we meet.

- Email + in-app notification when a shadowbanned player signs up to any
  session at an event where the banner runs a scheduled session.
- The notification discerns the two cases: signed up *somewhere at the
  event* vs. signed up *into a session where the banner is a player*
  (confirmed, waiting, or holding an offered seat). The second case names
  the session and also reaches banners who present nothing at the event.
- The enrollment page frontloads a warning listing shadowbanned players
  already occupying a seat in that session, with the ban date.
- Avatars of players the viewer shadowbanned get a red ring on event cards
  and warnings.

## Managing the list

As a player, I want to manage my shadowban list in Settings → Safety, so
that bans stay under my control.

- Add by username or email with a neutral confirmation (no account
  enumeration), or pick from "players you have met" (people who played the
  banner's sessions or alongside them, both seats confirmed).
- Bans are liftable; active bans sort first.
