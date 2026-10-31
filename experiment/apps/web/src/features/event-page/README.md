# Event page

`/event/<slug>/`, the port of Django's `EventPageView` and `chronology/event.html`.

| File | Holds |
| --- | --- |
| `view.ts` | The page: hero, notices, enrolled banner, schedule region, propose call to action, session dialog, back link. |
| `hero.ts` | `[data-event-hero]`: cover, status pills, description, add-to-calendar menu, facts rail, program CTAs, print and map tools. |
| `filters.ts` | Search box, filter panel (dropdown, and a dialog under 30rem), the four comboboxes, chips, the no-results state. |
| `session-card.ts` | The card, its `data-*` filter contract, tags cloud, location crumbs, seat label. |
| `schedule.ts` | Card days (small events), the ledger and rooms grid (20+ sessions), the hour rail, day folding, view tabs. |
| `modal.ts` | The session dialog: header, Information and Participants panels, the enrollment footer. |

State lives in `client/event-page/`: `flags.ts` is what the loader in `server/pages/event-page.ts` computes from the `readEventPage` capability, `filters.ts` parses and serialises the query string (`q`, `enrollment`, `hide-ended`, `status`, `space`, `age`, `age-min`, `day`, `hour`, `track`, `category`, `tag-<slug>`, `host`), `update.ts` keeps the Model and the URL in step (`replaceUrl` for filters, `pushUrl` for `?session=` and `?view=`).

## Enrollment actions

The dialog footer renders `model.enrollment`, an `EnrollmentActions` value from `client/event-page/enrollment-slot.ts`. `NotAvailable` renders nothing; `SignInToEnroll` renders the sign-in link a signed-out reader gets on an enrollable session.

To plug enrollment in:

1. Add the cases the footer needs to `EnrollmentActions` (enroll, waitlist, cancel, opens-at) and render each in `footer` in `modal.ts`.
2. Add the clicks and results to `EnrollmentSlotMessage`; they reach the page wrapped in `EventPageMessage.GotEnrollmentMessage`, which `updateEventPage` currently answers with the Model unchanged.
3. Compute the value in `enrollmentFor` in `client/event-page/update.ts` (called whenever the dialog opens) and in `initEventPage` for a cold `?session=` load. The open session is `model.openSession`; its card is the `SessionView` with that id in `model.sessions`.
4. After an enrollment RPC succeeds, write the new seats into that `SessionView` (`enrolledCount`, `waitingCount`, `spotsLeft`, `userEnrolled`, `userWaiting`) so cards, filters and the dialog agree without a reload.
