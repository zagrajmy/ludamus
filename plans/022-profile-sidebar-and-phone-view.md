# 022: Profile sidebar and phone view

Priority: P2. Effort: L. Depends on: nothing. Issue: #1676.
Mockups: [desktop, idea C](https://claude.ai/artifact/5n38CnLVjPnooNtwtcRqVx#page-dcb81aee8d83),
[phone prototype](https://claude.ai/artifact/NvFrf4KRawfSFUS4wBLviH#page-dcb81aee8d83).

## Job

A signed-in user wants one profile setting and must find it. Today six tabs
overflow the bar and scroll sideways, so some stay hidden. Success: every
section is reachable without horizontal scrolling on desktop and on a phone,
and everything the tabs offer still works.

## Core decision: one page, two layouts

Every section stays a real server-rendered URL. Each page renders the same DOM:
identity card, section nav, section content. Width decides the layout.

- `lg` and up: sidebar beside a content card.
- Below `lg`: the card and nav are the page, and the section content is a bottom
  sheet over them.

Rows are plain links, so opening a section is a full navigation. Views, POST
handlers, redirects, `?invite=`, and flash messages stay as they are. No partial
responses, no htmx, no second copy of any form. The cost is a page load per
section. If that feels slow on a phone, `hx-boost` with `hx-select` on the rows
can come later without changing the server.

`/crowd/profile/` is the one collision: it is Personal Information on desktop
and the bare index on a phone. Below `lg` the Personal sheet stays closed unless
the URL is `#personal` or the form has errors. The Personal row links to
`#personal`, and so does the email banner's "Go to profile". Every other section
renders its sheet open.

The sheet is a `div`, not a `<dialog>`, for three reasons:

- The same element is a static card on desktop.
- A top-layer dialog would cover `.flash-region`.
- It matches the schedule's filter sheet (`session-filters.ts`): `aria-modal`
  set by JS only at sheet width, Tab wraps at the ends, the stylesheet keys the
  scroll lock off `aria-modal`.

SAFETY: never put `inert` on the sheet's siblings. `confirm-dialog` and the
flash region live there, and a modal inside an inert subtree stays inert.

## Answers to the issue's open questions

These are proposals until the maintainer confirms them.

| Question | Proposal |
| --- | --- |
| Direct link to a section on a phone | Index with that section's sheet open at its default height. |
| Back with a sheet open | Ordinary browser back: to the index if the user came from it, otherwise to the previous page. |
| Close, drag down, or tap the backdrop | `history.back()` when the referrer is the index, otherwise `location.replace` to the index, so a user from an email lands in the profile and not outside the site. |
| Half-filled form dragged away | Dirty forms stop the dismiss: the sheet snaps back and the shared `confirm-dialog` asks to discard. `beforeunload` covers browser back. No autosave. |
| Where validation errors appear | Server re-render with the sheet open, full height, inline `tessera_field` errors, first error scrolled into view. The existing warning flash sits above the sheet (`z-60`). |
| Width that switches to the phone view | `lg` (1024px), as in the organizer panel. The layout needs about 900px (264 sidebar, 560 content, gaps), so `md` cannot hold it. |

## Steps

One branch, one PR, one commit per step. Each step is usable through the UI.

### 1. Desktop sidebar

- Replace the tab shell in `crowd/user/profile_base.html` with a two-column
  layout. Widen the wrapper from `max-w-3xl` to the mockup's width.
- Add the identity card: `components/avatar.html`, name, email, and a "Change
  avatar" link to `web:crowd:profile-avatar`.
- Replace `_profile_tabs.html` with a nav of links using `aria-current="page"`.
  Copy the look from `panel/parts/sidebar-link.html`. Sections: Personal
  Information, Parties, Safety, Notifications, Privacy.
- Avatar leaves the nav. Its page keeps its URL, with no nav item current.
- Below `lg` the sidebar stacks above the content, so this step already ends the
  sideways scrolling on phones.
- Update the e2e specs that look for `tab` roles: `profile.auth.spec.ts` and its
  neighbours, using link and `aria-current` assertions.

### 2. Bottom sheet component

- Add `components/bottom-sheet.html`, `client/src/bottom-sheet.ts`, and
  `bottom-sheet.css`, plus an entry in the `/design/` gallery.
- Heights: half and full snap points. The prototype's 60px drag threshold is a
  sensible start: up goes full, down from full goes half, further down closes.
- The handle is a real button: Enter toggles the snap, and it has an `aria-label`
  for the state. Esc closes. Drag uses pointer events.
- Respect `prefers-reduced-motion`, safe-area insets, and `--modal-max-h`-style
  visible-viewport sizing. Animate height, not `transform`, so `position: fixed`
  descendants stay put.
- Focusing a text input snaps the sheet to full, and visual-viewport sizing lifts
  it over the keyboard. `scripts/ios-regressions/` still needs a device case.

### 3. Phone view

- Below `lg`, `profile_base.html` wraps `profile_content` in the sheet.
- Sections set height through a template block: half by default, full for
  Parties and Safety. Sub-pages `party_detail.html` and `age_range.html` are
  full and name their parent as the close target, so closing returns to Parties
  or Privacy.
- Implement the `#personal` case and the Close, Back, and direct-link rows above.
- Skip the entrance animation when the referrer is the same path. Otherwise each
  mute or form post replays the slide-up. Keep the snap per path in
  `sessionStorage` for the same reason.
- Check that `data-menu-panel` kebab menus on Parties are not clipped by the
  sheet's scroller. Nested modals are top-layer and need no change.
- Add e2e coverage in the existing iPhone project: open each section, close, back,
  direct link.

### 4. Status hints and invitation badge

- Add a `takes_context` simple tag (`panel_tags` is the precedent) that reads a
  summary DTO from `request.services`, so no view's `context_data` changes.
- Only real values. Empty values show no count. Mockup numbers are not
  requirements.

| Row | Hint | Source |
| --- | --- | --- |
| Personal Information | "Name, email, Discord", or unverified email state | `current_user` |
| Parties | Parties and companions counts, badge for pending invites | `parties.counts` |
| Safety | Shadowbanned count | shadowban service |
| Notifications | Subscriptions and muted counts | `list_for_user` |
| Privacy | Age band | `current_user` |

- The hints render on every profile page, because the server cannot see the
  width. A light `parties.counts` read keeps that cheap: `overview` loads every
  member of every party.

### 5. Dirty guard and finish

- Add the dirty-form guard and the validation-error behaviour from the table.
- Run `mise run messages`, fill the Polish entries, and resolve fuzzy ones.
- Add a Playwright case for the dirty guard and one for a validation error in a
  sheet. Add the sheet to `coverage-gaps.md` under mobile navigation, or to
  `patterns.md` if it is promoted.
- `mise run shots` at both widths for the PR. Run `mise run lint:impeccable` and
  `lint:ast-grep`, then `fullcheck`.

## Out of scope

- New sections or settings. #669 (Proposals) adds a row later; the nav fits it.
- Renaming `profile_active_tab`. It is a misnomer now, but the rename touches
  about twenty test assertions for no behaviour.
- `components/tab-shell*` stays: the panel still uses it.

## Check while building

- #584 reports missed click sounds across profile tabs. Confirm where the sounds
  attach, so the sidebar and rows keep them.
- The analytics choice may live only in the browser. If so, the Privacy hint
  stays age band only.

## STOP conditions

- A section needs a server change beyond the template to work in a sheet.
- The iOS keyboard case cannot be solved with visual-viewport sizing.
