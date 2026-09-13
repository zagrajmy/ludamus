---
status: draft
updated: 2026-09-13
---

# Session state

## Three facts, shown together

As an organiser, I want every place that shows a session's state to show
three things side by side: its bucket, whether it is on the timetable, and
whether its schedule is confirmed, so that I never have to infer one from
another.

As an organiser, I want a session's bucket shown with the icon and colour I
gave it, so that I can read a list of sessions at a glance.

As an organiser using assistive technology, I want each of the three facts
announced in words rather than shown by icon or colour alone, so that I
learn a session's state without seeing the screen.

As an organiser, I want the same session to show the same state on every
page, so that I stop seeing a session labelled one way in a list and
another way on its own page.

## Moving sessions between buckets

As a reviewer, I want to move a proposal to any bucket from where I am
reading it, so that I can decide without returning to the list.

As a reviewer, I want to move several proposals to a bucket at once, so
that I can clear a queue quickly.

As a reviewer, I want a bulk move to tell me how many were moved, how many
were refused because they are on the timetable, and how many no longer
exist, so that I know exactly what happened.

As an organiser, I want a session placed on the timetable to be refused a
move out of every ready-to-plan bucket, so that nothing on the timetable
sits in a bucket that forbids planning.

As an organiser, I want to be refused when I try to put a session on the
timetable while it is not in a ready-to-plan bucket, so that the timetable
only ever holds sessions my workflow has cleared.

As an organiser, I want a session taken off the timetable, deleted, or
restored to keep its bucket, so that its place in my workflow does not
change behind my back.

As a reviewer accepting a proposal straight into a slot, I want the
session to land in the first ready-to-plan bucket, so that the shortcut
and the long way produce the same state.

As a maintainer creating sessions through the programme tools, I want them
to land in the first ready-to-plan bucket unless I name another, so that
bulk-created programme is ready to place.

## Finding sessions

As a reviewer, I want to filter the session list by bucket, so that I can
focus on one step of the workflow.

As a reviewer, I want to filter separately by whether a session is on the
timetable, so that placement is never mixed into the bucket choice.

As a reviewer, I want to filter separately by whether a session's schedule
is confirmed, so that I can find the ones still waiting on a facilitator.

As a reviewer, I want the session list to open on the inbox bucket showing
only sessions not yet on the timetable, so that my work surface is in
front of me when I arrive.

As a reviewer, I want the three filters to combine with search, track and
category, so that I can narrow the list along several axes at once.

As a reviewer, I want to sort sessions by bucket order, so that the list
follows the workflow.

## Counting and reporting

As an organiser, I want the timetable overview to count sessions per
bucket and per track, in bucket order, so that I can see how far each
track is through the workflow.

As an organiser, I want the confirmation tracking pages to list a
facilitator's sessions that are not on the timetable with their bucket, so
that I can tell them where each stands when I write.

As an organiser, I want the call-for-proposals overview to count as
accepted only sessions in a ready-to-plan bucket, so that rejected and
on-hold proposals no longer inflate the figure.

As a participant, I want the public programme to keep showing exactly the
sessions on the timetable in public tracks, so that the redesign changes
nothing I see.

## Continuity

As an organiser of an existing event, I want every session to appear in
the bucket matching its former status the day this lands, so that nothing
visibly changes until I change it.

As an operator, I want the switch from statuses to buckets to happen in
two releases, the second removing what the first replaced, so that a
release can be rolled back without losing data.
