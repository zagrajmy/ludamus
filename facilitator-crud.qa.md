# Manual Test Scenarios

Based on: `facilitator-crud-improvement` vs `main`
Environment: staging, with the facilitators already imported from the Google
Sheet. Nothing to set up — click through the panel as an organizer.

---

## Facilitator list — search

### Find a facilitator by name

**Preconditions:** Panel → an event → Facilitators.

- [ ] Type part of a facilitator's name into **Search**, press **Filter** →
      Expected: only matching rows; the search box keeps the text; a **Clear**
      button is offered.
- [ ] Type the same thing in a different case → Expected: same matches.
- [ ] Search a name with Polish diacritics, spelled exactly → Expected: found.
- [ ] Press **Clear** → Expected: the full list is back and the box is empty.

### Find a facilitator by what they answered

- [ ] Pick a facilitator, open their detail page, copy a value from a **text**
      personal-data field (phone, e-mail, whatever the sheet had), search for it
      → Expected: that facilitator is in the results.
- [ ] Search for a value that only exists in a **select** or **checkbox** field
      → Expected: no match (only text fields are searched) — the page must still
      render the "no matches" state, not blow up.
- [ ] Search for the name of a **linked user account** that differs from the
      facilitator's display name → Expected: the linked facilitator shows up.

### No matches

- [ ] Search for gibberish → Expected: "No facilitators match your filters." with
      a **Clear filters** link; the filter bar stays visible.

### The imported data doesn't duplicate rows

- [ ] Search for something that matches a facilitator who has **several
      sessions** → Expected: they appear exactly **once**, and their Sessions
      count is the real number (not doubled or tripled by the search).

---

## Facilitator list — filters

### Accreditation

- [ ] Pick an accreditation from the dropdown, **Filter** → Expected: only those
      facilitators; the dropdown keeps the choice after reload.
- [ ] Pick "All accreditations", **Filter** → Expected: everyone is back.

### Personal-data fields

- [ ] Look at the filter bar → Expected: there's a control for each
      **single-choice select** and **checkbox** field, and **none** for text
      fields or multi-choice selects.
- [ ] Pick an option in a select-field filter, **Filter** → Expected: only
      facilitators who answered exactly that; the choice sticks after reload.
- [ ] Tick a checkbox-field filter, **Filter** → Expected: only facilitators who
      answered yes.
- [ ] Untick it, **Filter** → Expected: the filter is gone — unticked must NOT
      mean "show only those who answered no".
- [ ] Combine a select filter with a checkbox filter → Expected: only
      facilitators matching **both**.
- [ ] Combine a field filter with a search term → Expected: results satisfy both.

### Flagged

- [ ] Flag someone (see below), tick **Flagged for deletion only**, **Filter** →
      Expected: only flagged rows, each with the red "Flagged" badge and tinted
      background.
- [ ] Untick, **Filter** → Expected: everyone is back.

---

## Facilitator list — sorting

- [ ] Click **Display Name** → Expected: sorts A→Z with a ▲ marker. Click again
      → Z→A with ▼.
- [ ] Click **Sessions** → Expected: sorts by session count; check the numbers in
      the column actually follow the order. Click again → reversed.
- [ ] Click **Accreditation** → Expected: rows group by accreditation type.
- [ ] Click **Linked User** → Expected: linked and unlinked rows group together
      (all the "None" ones on one side).
- [ ] Add a personal-data column (next section), click its header → Expected:
      sorts by that field's value; facilitators with no answer group together.

### Sorting has to survive filters and paging

- [ ] Search for something, then click a column header → Expected: the search is
      still applied (still in the box, still filtering) and the sort is applied
      on top.
- [ ] Sort by a column, then press **Filter** with a new search term → Expected:
      the sort direction survives the submit.
- [ ] With 500 imported facilitators the list is paginated: sort, then click
      **Next** → Expected: page 2 keeps the same sort **and** the same filters.
- [ ] On page 2, click a column header → Expected: you land back on page 1 with
      the new sort, not on a page 2 of a re-sorted list.
- [ ] Page through to the last page and back → Expected: **Previous**/**Next**
      appear/disappear correctly, "Page N of M" is right.

---

## Facilitator list — columns

### Choose what's shown

- [ ] Open the **Columns** tab (the list page has List / Merge / Columns tabs) →
      Expected: an ordered list with the four built-in columns (Display Name,
      Linked User, Sessions, Accreditation) already ticked at the top, and every
      personal-data field of the event unticked below.
- [ ] Tick two fields, **Save** → Expected: "Columns updated.", back on the list,
      two new columns before Actions.
- [ ] Drag a ticked column to a different position, **Save** → Expected: the
      list's column order follows.
- [ ] Untick a built-in column (e.g. Sessions), **Save** → Expected: it's gone
      from the list.
- [ ] Read a few cells against the facilitators' detail pages → Expected: each
      row shows its **own** value; people who didn't answer get an empty cell,
      never somebody else's answer.
- [ ] Add a **checkbox** field as a column → Expected: cells read "Tak"/"Nie",
      not `True`/`False`.
- [ ] Add a field with long imported values (a description, an address) →
      Expected: the cell truncates and hovering shows the full value as a
      tooltip; the table doesn't blow out sideways.
- [ ] Add a multi-answer field → Expected: values shown comma-separated on one
      line.
- [ ] Untick everything, **Save** → Expected: the list falls back to the four
      built-in columns — field columns gone, built-ins back even if unticked.
- [ ] Log out, log back in, open the list → Expected: your column choice is still
      there (it's saved per event, not per session).

### Columns are per event

- [ ] Set columns on this event, then open another event's facilitators list →
      Expected: no extra columns there; its Columns page offers only its own
      fields.

---

## Triage actions (flag / unflag / mark as guest)

### Flag for deletion

- [ ] Click the **flag** icon on a row → Expected: "Facilitator flagged for
      deletion.", the row goes red-tinted, a "Flagged" badge appears next to the
      name, and the flag icon becomes an undo arrow.
- [ ] Do this from a **filtered, sorted, page-3** view → Expected: after the
      action you're back on exactly that view — same search, same sort, same page
      — not thrown back to page 1.
- [ ] Click the **undo** icon → Expected: "Facilitator unflagged.", badge and
      tint gone.
- [ ] Open the flagged facilitator's detail page → Expected: nothing was deleted
      — sessions and personal data are all still there. Flagging is only a
      marker.

### Mark as guest

- [ ] Click the **user-plus** icon on someone who isn't a guest → Expected:
      "Facilitator marked as guest.", the Accreditation cell now shows the guest
      label, and the icon disappears from that row.
- [ ] Open their detail page and look at the change history → Expected: the
      accreditation change is logged, old → new, with you as the author.
- [ ] Confirm the icon is **not** offered on rows that are already guests.

### When it can't work

- [ ] While the list is open in one tab, delete/merge away a facilitator in
      another tab, then click flag on the stale row → Expected: "Facilitator not
      found." and a clean redirect back to the list — no error page.

---

## Internal comment

### Add, edit, remove

- [ ] Click **Edit** on a facilitator → Expected: the page shows the read-only
      Display Name, the Accreditation dropdown, a new **Internal comment**
      textarea with "Visible to organizers only.", and the Personal Information
      card below.
- [ ] Type a multi-line comment, **Save** → Expected: saved; reopening Edit shows
      it in the textarea.
- [ ] Open the **detail** page → Expected: an "Internal comment" block with the
      line breaks preserved and the organizers-only note.
- [ ] Clear the comment, **Save** → Expected: the block disappears from the
      detail page entirely (no empty heading left behind).
- [ ] Type only spaces, **Save** → Expected: treated as empty, no empty block.
- [ ] Type `<b>bold</b>` into the comment, **Save** → Expected: the detail page
      shows the literal text, not bold text.
- [ ] Paste a long paragraph (a real rejection reason, a few hundred words) →
      Expected: saved whole, no truncation, no error.

### One save, everything saved

- [ ] In a single Save: change the accreditation, write a comment, and change a
      personal-data answer → Expected: all three stick, and the change history
      records **one** edit entry, not three.
- [ ] Change **only** the comment → Expected: the accreditation is unchanged
      afterwards (check the dropdown after reload).
- [ ] Change **only** the accreditation → Expected: an existing comment is still
      there afterwards, not wiped.

### It must never reach attendees

- [ ] Put a comment on a facilitator who runs a public session, then open that
      session's public page while logged out → Expected: the comment appears
      nowhere.

---

## Regressions on the imported data

- [ ] Open a facilitator with **no** comment → Expected: the detail page looks
      exactly as before, no empty "Internal comment" block.
- [ ] Create a facilitator via **New Facilitator** → Expected: still works;
      appears in the list, unflagged, no comment.
- [ ] Merge two of the imported duplicates via the **Merge** tab → Expected:
      "Facilitators merged successfully."; the merged-away row is gone from the
      list and the survivor's Sessions count is the combined number, each session
      counted once.
- [ ] Merge a **flagged** duplicate into a clean one → Expected: no error; check
      what happened to the survivor's flag and comment and decide whether that's
      what you want.
- [ ] Rename a personal-data field that's currently used as a column → Expected:
      the list's column header and filter label pick up the new name.
- [ ] Delete a personal-data field that's currently used as a column → Expected:
      the facilitators list still loads and just drops that column.
- [ ] Submit a proposal through the public wizard → Expected: personal-data
      fields still render and save (that code path was touched).
