# Zagrajmy landing notes

## Landing page draft

Draft rules:

- Polish is the source copy.
- English follows Polish closely.
- Primary audience: organizers of conferences and meetups.
- Secondary audience: programme submitters, GMs, attendees.
- Primary CTA: `mailto:kontakt@zagrajmy.net`.
- No self-serve promise.
- No AI mention in page copy.
- Use real event assets and screenshots.
- Show how the system works with interactive widgets, not only prose.
- Include testimonials, but only real quotes from real organizers/participants.

### Meta

PL title: Zagrajmy - organizacja programu konferencji i meetupów

PL description: Pomagamy organizatorom zbierać zgłoszenia, układać program,
publikować stronę wydarzenia i prowadzić zapisy w jednym miejscu.

EN title: Zagrajmy - conference and meetup programme planning

EN description: We help organizers collect proposals, build the programme,
publish event pages, and run enrollment in one place.

### Hero

Eyebrow PL: Dla organizatorów konferencji i meetupów

Eyebrow EN: For conference and meetup organizers

Headline PL: Zorganizuj konferencję albo meetup bez chaosu w arkuszach

Headline EN: Run a conference or meetup without spreadsheet chaos

Subheadline PL: Przychodzisz z wydarzeniem. My pomagamy ustawić zgłoszenia,
program, zapisy i stronę wydarzenia w Zagrajmy.

Subheadline EN: Bring the event. We help set up proposals, programme,
enrollment, and the public page in Zagrajmy.

Primary CTA PL: Zorganizuj wydarzenie z Zagrajmy

Primary CTA EN: Run your event with Zagrajmy

Primary CTA destination:
`mailto:kontakt@zagrajmy.net?subject=Wydarzenie%20na%20Zagrajmy`

CTA microcopy: Show `kontakt@zagrajmy.net` as visible, copyable text next to the
button (tessera copy-to-clipboard component). `mailto:` silently fails for
webmail users with no mail client configured; the visible address is the
fallback.

Secondary CTA PL: Zobacz wydarzenia

Secondary CTA EN: Browse events

Secondary CTA destination: `#events`

Hero visual: Use an interactive product preview, inspired by Cursor's "show the
interface first" approach. Default state should show a real event page. Let the
visitor switch between:

- public event page
- proposal form
- organizer timetable
- enrollment/waiting list view
- printable materials

Fallback if the widget is too much for the first build: Use a composed
screenshot set with the same five states. Avoid abstract illustration.

### Proof strip

PL: Zagrajmy działa na prawdziwych wydarzeniach: od publicznej strony programu
po zapisy i materiały do druku.

EN: Zagrajmy runs real events: public programmes, enrollment, and print
materials included.

Asset direction: Show real event cards, event covers, or screenshots. If no
testimonial exists, do not fake one.

Honest numbers option: We can't fake testimonials, but real aggregate counts
from the production DB are fair game and cheap: "N wydarzeń, M punktów programu,
K zapisów". Only ship if the numbers are big enough to impress; a "3 wydarzenia"
strip hurts more than it helps. Check the numbers before deciding.

### Interactive product walkthrough

Intent: This is the main "show, don't tell" section. It should behave more like
a small product demo than a marketing section.

Heading PL: Zobacz, jak wydarzenie przechodzi przez Zagrajmy

Heading EN: See how an event moves through Zagrajmy

Body PL: Od pierwszych zgłoszeń po publiczny program i zapisy. Pokażmy to na
przykładzie jednego wydarzenia, bez slajdów i bez zgadywania.

Body EN: From first proposals to public programme and enrollment. Show it with
one real event, not with slides.

Widget idea:

1. Zgłoszenia
   - Show programme proposal form.
   - Highlight custom questions, contact data, preferred time slots.

2. Akceptacja
   - Show organizer view with proposals.
   - Highlight status, category, creator, missing info.

3. Harmonogram
   - Show timetable grid.
   - Highlight rooms, tracks, time slots, conflicts.

4. Publikacja
   - Show public event page.
   - Highlight programme cards, filters, covers.

5. Zapisy
   - Show enrollment state.
   - Highlight limits, waiting list, participant status.

6. Druk
   - Show printable timetable/door card preview.
   - Highlight "ready for venue" output.

Interaction:

- Desktop: segmented control or tabs on the left, live preview on the right.
- Mobile: horizontal stepper above preview.
- Each step should include one short sentence and one visible screenshot/state.
- Use real screenshots first. If needed, use seeded demo data that looks like a
  conference/meetup, not only RPG.

Copy labels PL:

- Zgłoszenia
- Akceptacja
- Harmonogram
- Publikacja
- Zapisy
- Druk

Copy labels EN:

- Proposals
- Review
- Schedule
- Publish
- Enrollment
- Print

### Problem

Heading PL: Program wydarzenia nie powinien mieszkać w pięciu miejscach

Heading EN: Your event programme should not live in five places

Body PL: Zgłoszenia w formularzu. Ustalenia w mailach. Zmiany sal w arkuszu.
Pytania od uczestników na czacie. Da się tak przeżyć jedno wydarzenie, ale nie
da się na tym spokojnie pracować.

Body EN: Proposals in a form. Decisions in email. Room changes in a spreadsheet.
Attendee questions in chat. You can survive one event like that, but it is a bad
way to work.

### Service

Heading PL: Nie dostajesz tylko narzędzia. Pomagamy ustawić proces.

Heading EN: You do not just get a tool. We help set up the process.

Body PL: Zaczynamy od tego, jak działa Twoje wydarzenie: kto zgłasza punkty
programu, kto je akceptuje, jak wygląda harmonogram, kiedy ruszają zapisy.
Dopiero potem ustawiamy Zagrajmy tak, żeby pasowało do tego sposobu pracy.

Body EN: We start with how your event works: who submits programme items, who
accepts them, how scheduling works, and when enrollment opens. Then we configure
Zagrajmy around that workflow.

Bullets PL:

- konfigurujemy zgłoszenia punktów programu
- pomagamy przenieść albo uporządkować istniejące dane
- ustawiamy bloki, sale i przedziały czasowe
- publikujemy stronę wydarzenia
- przygotowujemy zapisy, listy rezerwowe i wydruki

Bullets EN:

- configure programme proposal forms
- help move or clean up existing data
- set up tracks, rooms, and time slots
- publish the event page
- prepare enrollment, waiting lists, and print materials

### What Zagrajmy handles

Heading PL: Jedno miejsce na program, zapisy i publikację

Heading EN: One place for programme, enrollment, and publishing

Cards PL:

1. Zgłoszenia programu Twórcy programu zgłaszają punkty programu przez
   formularz. Możesz dodać własne pytania i wymagane informacje.

2. Układanie harmonogramu Pracujesz na salach, blokach i przedziałach czasowych.
   Widzisz konflikty zanim trafią do publicznego programu.

3. Strona wydarzenia Uczestnicy widzą aktualny program, opisy punktów programu i
   informacje o zapisach.

4. Zapisy i listy rezerwowe Ustawiasz limity miejsc, a zapisami uczestników i
   listą rezerwową zajmuje się Zagrajmy.

5. Materiały na miejscu Drukujesz harmonogramy i karty na drzwi bez ręcznego
   składania plików w ostatniej chwili.

Cards EN:

1. Programme proposals Programme creators submit items through a form. You can
   add your own questions and required fields.

2. Scheduling Work with rooms, tracks, and time slots. Catch conflicts before
   they reach the public programme.

3. Event page Attendees see the current programme, item descriptions, and
   enrollment information.

4. Enrollment and waiting lists You set the capacity; Zagrajmy runs enrollment
   and the waiting list.

5. On-site materials Print schedules and door cards without rebuilding files by
   hand at the last minute.

### Testimonials

Important: Do not invent testimonials. This section needs real people, real
roles, and permission to quote.

Heading PL: Od organizatorów, którzy już dowieźli program

Heading EN: From organizers who already shipped their programme

Intro PL: Najlepszy dowód to spokojniejsze przygotowania, mniej ręcznego
przepisywania i program, który uczestnicy mogą otworzyć na telefonie.

Intro EN: The best proof is calmer preparation, less manual copying, and a
programme attendees can open on their phones.

Layout:

- 3 quote cards if we have them.
- Each card: quote, name, role, event, optional avatar/logo.
- Put one stronger quote near the hero only after we have a real one.

Placeholder structure:

> "[real quote about setup, programme, enrollment, or less spreadsheet work]"
> Name, role, event

Good quote prompts to collect:

- What did Zagrajmy replace for you?
- What part saved the most organizer time?
- What changed for people submitting programme items?
- What changed for attendees?
- Would you use it again for the next edition?

If we do not have quotes before implementation: Ship the page without
testimonials or use a "Used for real events" screenshot strip. Do not publish
fake praise.

### How it works

Heading PL: Jak wygląda start

Heading EN: How we start

Steps PL:

1. Piszesz do nas Opisz wydarzenie, format programu i to, co dziś robisz
   ręcznie.

2. Ustawiamy strukturę Przygotowujemy wydarzenie, formularze zgłoszeń, sale,
   bloki i przedziały czasowe.

3. Otwierasz zgłoszenia albo importujesz dane Możesz zacząć od świeżych zgłoszeń
   albo uporządkować to, co już masz.

4. Publikujesz program i zapisy Uczestnicy dostają jedną stronę z aktualnym
   programem i zapisami.

Steps EN:

1. Contact us Tell us about the event, programme format, and what you handle
   manually today.

2. We set up the structure We prepare the event, proposal forms, rooms, tracks,
   and time slots.

3. Open proposals or import data Start fresh or clean up what you already have.

4. Publish programme and enrollment Attendees get one page with the current
   programme and enrollment.

### Events section

Heading PL: Wydarzenia w Zagrajmy

Heading EN: Events on Zagrajmy

Body PL: Zobacz publiczne wydarzenia, programy i strony, które już działają na
Zagrajmy.

Body EN: See public events, programmes, and pages already running on Zagrajmy.

Implementation note: Keep current upcoming/past event cards here. Do not bury
them below too many marketing sections.

### Final CTA

Heading PL: Masz wydarzenie do ogarnięcia?

Heading EN: Have an event to run?

Body PL: Napisz do nas. Pomożemy przełożyć Twój proces na Zagrajmy i przygotować
pierwszą wersję wydarzenia.

Body EN: Write to us. We will help map your process into Zagrajmy and prepare
the first version of your event.

Primary CTA PL: Zorganizuj wydarzenie z Zagrajmy

Primary CTA EN: Run your event with Zagrajmy

Primary CTA destination:
`mailto:kontakt@zagrajmy.net?subject=Wydarzenie%20na%20Zagrajmy`

CTA microcopy: Repeat the visible, copyable email address here too.

Secondary CTA PL: Zobacz wydarzenia

Secondary CTA EN: Browse events

Secondary CTA destination: `#events`

### Copy notes

- Prefer "program" in Polish marketing copy.
- Use project term "punkt programu" where the UI talks about individual
  submitted items.
- Use "przedział czasowy", not "blok czasowy".
- Do not promise self-serve event creation.
- Do not mention AI, agents, automation, or "service as software" on the public
  page. Hard rule for all public marketing surfaces: the page talks about
  outcomes and the event workflow, never about tooling or how the sausage is
  made.

## What I read

- `src/ludamus/templates/index.html`: `/events/` is mostly a list:
  announcements, upcoming events, past events, empty state.
- `src/ludamus/adapters/web/django/views.py`: `/` redirects to `/events/` unless
  the sphere defaults to encounters. The events page already uses services and
  DTOs.
- `src/ludamus/templates/base.html`: meta copy is still generic
  (`Event webapp`). OG image falls back to the logo.
- `src/ludamus/templates/components/event_card.html`: event cards are already
  good enough to reuse. Cover, date, session count, live/proposal/unpublished
  badges.
- `src/ludamus/templates/chronology/event.html`: event detail pages have the
  real public product: cover, statuses, sessions, enrollment, proposal state.
- `src/ludamus/templates/chronology/propose/base.html`: proposal wizard exists.
- `src/ludamus/templates/panel/index.html`: organizer dashboard shows sessions,
  hosts, rooms, proposals.
- `src/ludamus/templates/panel/timetable.html`: scheduling grid, conflicts,
  filters, print controls.
- `src/ludamus/templates/panel/import.html`: Google Docs import exists.
- Tests that probably move if headings change:
  `tests/integration/web/test_index_page.py`, `tests/e2e/tests/index.spec.ts`.

## My read

Right now a cold visitor lands on a list of events. That is useful if they
already know what Zagrajmy is. It does not explain why an organizer should care.

The landing page should probably sell the organizer side first, then keep the
event list close by for attendees. The product has enough real things to talk
about: proposals, scheduling, enrollment, waiting lists, print, imports. No need
for grand product language.

## Audience

Primary: Organizers of conferences and meetups.

Secondary: People submitting programme items, GMs, and attendees.
Attendee-specific needs overlap with encounters.

Open problem: Polish copy comes first, but the page should support both Polish
and English.

## Positioning options

1. Run conferences and meetups without spreadsheet chaos
   - Clear.
   - Says what pain we are solving.
   - Better fit for the primary audience.

2. Collect proposals, build the programme, publish the event
   - More literal.
   - Less punchy.
   - Probably better for a product page than a hero headline.

3. Run a programme-heavy event without rebuilding the same spreadsheet stack
   every time
   - Good if we want to cover conferences, meetups, RPG events, and mixed
     formats.
   - Longer, but closer to what the app actually does.

I would start with 1 in Polish, then make the English version match it closely.

## Hero draft

Headline: Run conferences and meetups without spreadsheet chaos

Subheadline: Collect session proposals, build the programme, publish event
pages, and manage enrollment in one place.

Primary CTA: Zorganizuj wydarzenie z Zagrajmy

CTA destination: `mailto:kontakt@zagrajmy.net`

Secondary CTA: Zobacz wydarzenia

No self-serve for now. The CTA should lead to contact/intake: "get in touch, we
will help you set it up."

English: Run your event with Zagrajmy

## Page shape

1. Hero
   - Talk to organizers.
   - Use a real product screenshot or event screenshot. No abstract art.
   - Keep events visible soon after the hero.

2. Events
   - Keep current announcements/upcoming/past behavior.
   - Rename only if useful. "Upcoming events" is fine.

3. The mess this replaces
   - Proposals in forms, Discord, mail, DMs.
   - Rooms and time slots changing late.
   - People asking where the current schedule is.
   - Enrollment and waiting lists handled by hand.

4. What Zagrajmy handles
   - Proposal collection.
   - Programme building.
   - Public event pages.
   - Enrollment and waiting lists.
   - Printable timetables and door cards.
   - Imports from existing forms.

5. How it works
   - Set up event structure.
   - Collect or import proposals.
   - Place sessions on the timetable.
   - Publish and run enrollment.

6. Proof
   - Use real events and screenshots.
   - Real assets, event names, and screenshots are allowed.
   - Use the open-source link if that helps.
   - Do not make up metrics or testimonials.
   - Add testimonial cards once real quotes are collected.

7. Final CTA
   - Attendees: browse events.
   - Organizers: `mailto:kontakt@zagrajmy.net`. No self-serve promise.

## Copy bits

Problem line: Your programme should not live in five Google Sheets, a Discord
thread, and one organizer's memory.

Benefit headings:

- Collect proposals without retyping them later
- Schedule sessions around rooms, tracks, and time slots
- Publish one page people can use on their phones
- Handle enrollment and waiting lists
- Print the on-site stuff everyone forgets until the last week

How-it-works labels:

- Define the event
- Collect proposals
- Build the timetable
- Publish enrollment

CTA options:

- Browse upcoming events
- See Zagrajmy in action
- Zorganizuj wydarzenie z Zagrajmy
- Run your event with Zagrajmy

## Service angle

There is no self-serve product pitch for now. Sell the result:

- You bring the event.
- We help configure Zagrajmy for it.
- You get proposal collection, programme, enrollment, and public pages without
  building the event stack yourself.

This can lean into "service as software": software-backed help, not pure SaaS.
Do not mention AI on the website.

Useful bits from the 7AI "Service as Software" page:

- Lead with outcomes, not feature inventory.
- Start with the client's goal and current workflow.
- Fit into existing tools/processes instead of forcing a fixed product ritual.
- Take repetitive operational work off the organizer.
- Show what gets done, not just what screens exist.

Adapted for Zagrajmy:

- We do not sell "access to software".
- We help you run the event programme.
- Zagrajmy is the toolset behind that service.
- The page should make the help feel concrete: setup, proposal forms, programme,
  enrollment, publishing, print.
- Avoid 7AI's language: "paradigm", "autonomous", "agents", "non-human work",
  "AI".

Possible service-led line: Przychodzisz z wydarzeniem. My pomagamy ustawić
zgłoszenia, program, zapisy i stronę wydarzenia w Zagrajmy.

English: Bring the event. We help set up proposals, programme, enrollment, and
the public page in Zagrajmy.

## Cursor-inspired direction

Cursor's page works because it shows the product surface immediately, then keeps
showing concrete workflows instead of only describing features. It also uses
named testimonials as proof.

Adaptation for Zagrajmy:

- Hero should include an interactive product preview, not a static decorative
  image.
- Feature sections should show real states: proposal form, organizer panel,
  timetable, public event page, enrollment.
- Testimonials should sit after the demo/product sections, when the visitor
  understands what the quote refers to.
- Final CTA stays contact-led.
- Do not copy Cursor's AI language, developer vocabulary, or download/self-serve
  flow.

## Implementation notes

- Likely start in `src/ludamus/templates/index.html`.
- Try not to touch `EventsPageView`; current context is enough for a first
  version.
- Keep `/events/` behavior.
- Add `title`, `meta_description`, OG/Twitter description blocks to
  `index.html`.
- Use existing styles/components: `{% icon %}`, `.btn`, `.card`, tessera where
  it fits.
- Wrap new strings in `{% translate %}`.
- Update tests that assert headings/copy.

## SEO draft

Superseded by the Meta section above — one canonical title/description pair, PL
first. Keeping the keyword list only.

Title: Use the Meta section titles (PL: "Zagrajmy - organizacja programu
konferencji i meetupów", EN: "Zagrajmy - conference and meetup programme
planning").

Meta description: Use the Meta section descriptions.

Possible keywords: conference programme software, meetup scheduling, event
proposal management, event enrollment, waiting list management, printable
timetable.

## Risks

- Organizer CTA is contact-led, not self-serve. Destination:
  `mailto:kontakt@zagrajmy.net`.
- Conference/meetup positioning is broader than the current RPG-heavy examples.
  Need screenshots/copy that make this believable.
- No testimonials or usage numbers found. Use real event assets/screenshots
  instead; do not fake proof.
- Polish copy is the source version. English should be translated from that, not
  written separately first.

## First build I would do

- Add a compact organizer-facing hero above the current event list.
- Keep current event sections.
- Add one short "what this replaces" section.
- Add one short benefits section.
- Add a "how it works" row.
- Improve metadata.

This should be mostly template work. No new service needed.

## Verification

- Run `mise run _pytest -- tests/integration/web/test_index_page.py`.
- Run the e2e index test if heading/copy changes affect it.
- Capture `/events/` screenshot with `mise run shots -- /events/`.
- Check desktop and mobile. Long event names and the empty state are the likely
  breakpoints.

## De-slop pass

What was wrong in earlier drafts:

- "Operating system" was ridiculous.
- Too many title-case framework headings.
- Too much fake certainty.
- Too much generic SaaS language.
- Not enough "here is the actual page we can build next".

Fixed by:

- Using plainer claims.
- Keeping the repo evidence.
- Calling out unknowns instead of smoothing them over.
- Making the first build smaller.

## Marketing pass (CRO + copywriting)

### Biggest issue: the page says the same thing four times

Hero widget (5 states), walkthrough (6 steps), "What Zagrajmy handles" (5
cards), Service bullets (5), How it works (4 steps) all enumerate proposals →
schedule → publish → enrollment → print. A visitor reads the list once; the
third repetition reads as padding and pushes the events section below the fold.
Collapse to **one enumeration, told two ways**:

- The walkthrough IS the feature list. Cut the "What Zagrajmy handles" cards
  entirely — every card duplicates a walkthrough step.
- Hero visual: one static screenshot (public event page) for v1, not a second
  widget. One interactive thing per page.
- Service bullets: keep — they answer "what do WE do for you", a different
  question than "what does the tool do". Trim to 4 by merging publishing into
  enrollment/print prep if it feels long.
- How it works: keep — it answers "what happens after I email you", which
  handles the biggest objection of a contact-led CTA (fear of a sales process).
  Consider renaming step 1 label from "Piszesz do nas" to include what happens
  next, e.g. add "odpowiadamy z planem konfiguracji" if true.

### Page order

1. Hero (static screenshot + both CTAs)
2. Proof strip (real covers, real counts if big enough)
3. Events (attendee traffic self-serves here fast; doubles as proof)
4. Problem
5. Service ("pomagamy ustawić proces")
6. Walkthrough (tabs; the one interactive section)
7. How it works
8. Final CTA

Rationale: most cold traffic is probably attendees looking for a schedule —
don't make them scroll through the organizer pitch. Organizers, the conversion
audience, will scroll.

### Headline alternatives (pick per taste, current one is fine)

PL current: "Zorganizuj konferencję albo meetup bez chaosu w arkuszach"

- "Program, zapisy i strona wydarzenia. W jednym miejscu, nie w pięciu."
  (mirrors the problem section, more concrete)
- "Ogarnij program wydarzenia bez pięciu arkuszy i jednego czatu" (casual,
  matches "Masz wydarzenie do ogarnięcia?" tone)

Keep headline and final-CTA tone consistent: current hero is neutral, final CTA
("do ogarnięcia") is casual. Either is fine; mixing is not.

### Service heading alternative

Current: "Nie dostajesz tylko narzędzia. Pomagamy ustawić proces." Leads with
negation. Alternative: "Pomagamy ustawić proces, nie tylko logowanie do
narzędzia." Low stakes, current is acceptable.

### v1 / v2 split

v1 (matches "First build I would do", plus):

- mailto links get `?subject=` prefill
- visible copyable email address next to CTA buttons (mailto fails silently for
  webmail users) — tessera copy component exists already
- walkthrough as plain tabs + static screenshots, no stepper, no widget

v2, only after v1 ships:

- interactive hero preview
- testimonials (once real quotes are collected)
- seeded conference-flavoured demo data for screenshots

## Open PRs to fold in (checked 2026-07-02)

Assume these merge before the landing ships.

### Party stack — #494 CRUD/invites, #495 enroll+promotion, #496 consent, #498 guests

Group enrollment, end to end: create a party, invite friends, add login-less
companions, enroll the whole group, **move up the waiting list together**,
leader can hold a seat a member confirms, and a "+N guests" stepper where the
organizer allows it. This is real differentiation vs Meetup/Luma-style
enrollment — say it.

Copy changes:

- Enrollment card 4 PL: "Ustawiasz limity miejsc, a zapisami, listą rezerwową i
  zapisami grupowymi zajmuje się Zagrajmy. Znajomi zapisani razem awansują z
  listy rezerwowej razem."
- Card 4 EN: "You set the capacity; Zagrajmy runs enrollment, waiting lists, and
  group signups. Friends who enroll together move up the waiting list together."
- Walkthrough step 5 (Zapisy) highlights: limits, waiting list, group
  enrollment, +N guests.
- Vocabulary caution: "drużyna" / "towarzysz" is the product UI term and it is
  RPG-flavoured. On the organizer-facing landing use neutral "zapisy grupowe" /
  "osoby towarzyszące"; keep drużyna vocab inside the product and on RPG-event
  pages.

### Proposal panel CRUD + audit trail — #459

Accept / on-hold / reject statuses, category + track + time-slot editing,
facilitator data editing, and change history on proposals and schedule.

Copy changes:

- Walkthrough step 2 (Akceptacja) highlights gain: statuses (accepted / on hold
  / rejected) and edit history.
- Optional service bullet: "widzisz historię zmian programu — kto, co, kiedy"
  (trust content for multi-organizer teams). EN: "full change history of the
  programme — who changed what, when".

### Screenshot timing

The enroll screen (#495 party selector, #496 consent matrix, #497 decline
offer, #498 guests stepper) and the panel proposal pages (#459) change
substantially in these PRs. Take walkthrough screenshots **after** the stack
and #459 merge, or they'll be stale on day one.

### Not for the page

MCP PRs (#490, #491, #499) — the notes already ban AI/agent language on the
public page. View transitions (#260) is polish, not copy.

## Unresolved

- Are production aggregate counts (events/sessions/enrollments) big enough to
  publish? Check before building the proof strip.
- Who collects the first real quotes, and from which past events?
- Do current screenshots look conference-like enough, or do we need seeded demo
  data before the walkthrough section ships?
