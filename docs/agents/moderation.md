# Moderation

How Zagrajmy staff handle reports and act on content, and what the Digital
Services Act asks of us while we are a micro enterprise (Art. 19 exempts us
from internal complaints, trusted flaggers, transparency reports and
Art. 28). Notes, not legal advice. Background and plans: #1755.

## Where things arrive

- **Notices of illegal content** come from the form at `/report/` (footer,
  event pages, session modals). Anyone can send one; reports of child sexual
  abuse or grooming may come without a name and email (Art. 16(2)(c)).
  Admin: _Content notices_.
- **Chat reports** come from "Report message" in the chat. Admin: _Parley
  reports_.
- Each one opens a **case**. Its reference, `Z-<id>`, starts the subject of
  every mail about it, and replies go to `staff@zagrajmy.net`
  (`settings.STAFF_EMAIL`, also the DSA point of contact named in the terms).
- Staff get a mail at that address for every new notice and chat report.
  Child-safety notices start with `[BEZPIECZEŃSTWO DZIECI]` (`[CHILD SAFETY]`
  in English): read those first.

## The staff inbox

`/staff/cases/` (staff only) lists every case by state, child safety first:
notices, chat reports, and mail to `staff@zagrajmy.net`, which the `posta`
mail Worker forwards to `/hooks/staff-mail`. A `[Z-n]` in the subject files
the mail under that case and reopens it; anything else opens a new one.
Replies sent from a case go out from the staff address with its reference in
the subject. Each case has a staff-only thread in the chat, where staff
talk it over and the server notes its events and mail, kept three years; the
`forget_case_mail` sweep deletes the case's mail after the same three
years. Deciding in the inbox does what the admin actions below do. The admin
stays the place to delete sessions, encounters and accounts.

## Deciding

1. Open the record in the admin and read it. For a chat report the admin
   holds the message as it was when reported.
2. Act on the content first, if it calls for it: delete the session or
   encounter, or the account, in the admin. A reported chat message goes
   with **Delete the reported messages for everyone** on _Parley reports_,
   which asks for the ground and decision text, deletes the message, and
   closes all its reports as actioned the way step 3 does.
3. Select the record, run **Decide on selected notices** (or **chat
   reports**), and fill in:
   - **Actioned** or **Rejected**;
   - for actioned: what was done and the ground (the law, or the point of
     § 4.1 of the terms). With the law as the ground, name the provision
     (e.g. art. 286 § 1 Kodeksu karnego); with a suspension, its last day;
   - the decision text. Both the reporter and the person affected read it, so
     state the facts and never name the reporter;
   - for a notice: the affected account, if there is one. Decide one notice
     at a time when you name it.
4. The action mails the reporter the outcome and their redress options, and,
   for an actioned report with an affected account, sends that person a
   statement of reasons (Art. 17) at the address on their account, proven
   or not. Everyone who reported one chat message shares its case, and its
   author gets one statement for it. The admin names anyone with no address
   on record; reach them another way. Closed reports cannot be edited.
5. Acting on content or an account without a report (something staff found
   themselves): on _Users_, run **Send a statement of reasons to selected
   users**. Before deleting an account, send it first, while the address is
   still on record.

Organizers delete messages and mute people inside the chat Worker. Those
actions do not yet send a statement of reasons; that needs the Worker to
report them back (TODO in `workers/parley/src/room-agent.ts`, #1755).

## Police and Dyżurnet.pl (Art. 18)

Report to the police (112 when someone is in immediate danger) whenever
content suggests a crime that threatens someone's life or safety: a threat
to kill or hurt, a plan to meet a child for abuse, self-harm in progress.

Child sexual abuse material and grooming go to
[Dyżurnet.pl](https://dyzurnet.pl/) (NASK's hotline), and to the police when
a child may be at risk now. Then:

- don't download, forward or keep copies of the material beyond the admin
  record; give Dyżurnet the URL and the case reference;
- remove the content and the account, and send the statement of reasons
  unless doing so would warn a suspect the police are after (ask them);
- note in the decision text that it was reported, and to whom.

## Appeals

Anyone can reply to a decision mail or write to `staff@zagrajmy.net`. Where
we can, the other owner reviews it, not the one who decided. Answer by
replying in the same thread, so the case reference stays in the subject.
If the decision changes, decide the record again by hand and say so in the
reply. Courts and UKE remain open to them either way; the mails say so.

## UKE's question about active users (Art. 24(3))

UKE, as Poland's Digital Services Coordinator, may ask for the average
monthly active recipients over the last six months. Answer within the
deadline they give, from `staff@zagrajmy.net`, with:

```sh
mise run dj monthly_active_recipients
```

It prints each of the last six full months and their average: accounts that
signed in or enrolled in that month. That is a floor, since people who only
read programmes without signing in are recipients too. Add the monthly
unique visitors from Cloudflare's analytics for the zone as the upper
estimate, and say which is which and how each was counted.
