---
status: draft
updated: 2026-09-13
---

# Session buckets

## Defining buckets

As an organiser, I want to define my own set of buckets for an event's
sessions, so that the workflow matches how my team actually processes
proposals.

As an organiser, I want to give each bucket a name, so that my team knows
what it means.

As an organiser, I want to give each bucket an icon and a colour, so that
a session's bucket is recognisable at a glance.

As an organiser, I want to pick the colour from a fixed set that fits the
rest of the panel, so that buckets stay readable in both light and dark
themes without me checking contrast.

As an organiser, I want to set the order of buckets, so that they appear in
the order sessions travel through them.

As an organiser, I want to mark a bucket as ready to plan, so that only
sessions that reach it can be put on the timetable.

As an organiser, I want to rename, recolour, reorder and re-flag a bucket
after sessions are already in it, so that I can adjust the workflow
mid-event.

## Which bucket receives new sessions

As an organiser, I want new proposals and imported sessions to land in the
first bucket in my order, so that there is one obvious inbox.

As an organiser, I want the bucket list to tell me that the first bucket is
the inbox, so that I do not discover it by surprise after reordering.

## Guard rails

As an organiser, I want to be refused when I try to delete a bucket that
still holds sessions, so that no session is left without a bucket.

As an organiser, I want to be refused when I try to delete the last bucket
of an event, so that new proposals always have somewhere to land.

As an organiser, I want to be refused when I try to remove the ready-to-plan
mark from a bucket that holds sessions on the timetable, so that nothing on
the timetable ends up in a bucket that forbids planning.

As an organiser, I want two buckets in one event to never share a name, so
that my team cannot confuse them.

As an organiser managing one event, I want to be unable to see or change
another event's buckets, so that events stay isolated from each other.

## Starting point

As an organiser creating an event, I want it to start with four standard
buckets: pending, accepted, on hold and rejected, with accepted marked
ready to plan, so that I can work immediately without configuring anything.

As an organiser of an existing event, I want those same four buckets to
appear already configured, so that the change costs me nothing on the day
it lands.

As a Polish-speaking organiser, I want the standard buckets and the bucket
pages in Polish, so that I can configure the workflow in my own language.

As an organiser using assistive technology, I want to manage buckets by
keyboard and hear an icon's meaning rather than only see it, so that the
configuration pages are not limited to sighted mouse users.
