# Police escalation runbook

Use this when anything on Zagrajmy (a report, a message, a session or
encounter description, a profile) suggests that someone's life or safety is
in danger, or that one of the crimes listed below was planned, tried or
committed.

This runbook names duties; it is not legal advice. For edge cases, ask
counsel (see [Contacts](#contacts)), but never wait for counsel before
calling 112.

## If someone is in danger right now

**Call 112.** Do it before anything else in this document. Say:

- who you are: a moderator of zagrajmy.net, an online platform for game
  events;
- what you saw and when (UTC time and your local time);
- anything that says where the person is: an event, a venue, a city;
- that you have kept the data and can send it.

Write down the time of the call and the operator's answers, then continue
with [Preserve the evidence](#preserve-the-evidence).

## Contacts

> **TODO (#1568): the default escalation contact and the backup are not
> decided yet.** Until someone fills this table, the person who found the
> content follows this runbook alone and tells both founders by phone
> afterwards.

| Role               | Name           | Phone          | Email          |
| ------------------ | -------------- | -------------- | -------------- |
| Escalation contact | _TODO (#1568)_ | _TODO (#1568)_ | _TODO (#1568)_ |
| Backup             | _TODO (#1568)_ | _TODO (#1568)_ | _TODO (#1568)_ |
| Legal counsel      | _TODO (#1568)_ | _TODO (#1568)_ | _TODO (#1568)_ |

The escalation contact has production access (Django admin, Coolify,
Cloudflare, PostHog, Auth0) and keeps the evidence. If you lack that access,
do the steps you can and hand the rest to them.

## When to escalate

Escalate when either of these holds. If you are unsure, escalate: a false
alarm costs the police one phone call.

### DSA Art. 18: a threat to life or safety

As a hosting service we must **promptly** tell the police or prosecutor when
we learn of information that gives rise to a **suspicion** that a crime
involving a threat to someone's life or safety has happened, is happening or
is likely to happen, and give them all the relevant information we hold.
Suspicion is enough; we don't need proof.

Typical cases: a credible threat to kill or hurt someone, a plan to meet a
child for sex, someone describing abuse they are suffering, a threat of
violence at an event.

### Criminal Code art. 240 § 1: a personal duty to report

Anyone with credible knowledge that one of these crimes is being prepared,
was attempted or was committed must report it to the police or prosecutor
without delay. The duty is yours personally, not the company's, and breaking
it carries up to 3 years in prison. Verified against the consolidated
Kodeks karny, Dz.U. 2026 poz. 1342.

- killing a person (art. 148), or taking a contract to kill someone
  (art. 148a);
- grievous bodily harm (art. 156): blinding, deafening, crippling, a
  life-threatening or lasting illness, permanent disfigurement;
- aggravated rape (art. 197 § 3–5): by two or more people, against a close
  relative, with a weapon or in a life-threatening way, against a pregnant
  woman, while recording it, against a child under 15, with particular
  cruelty, or causing grievous harm or death;
- a sexual act with a helpless or mentally impaired person, exploiting that
  state (art. 198);
- a sexual act with a child under 15 (art. 200 § 1), and showing a child
  under 15 pornography or a sexual act (art. 200 § 3–5);
- depriving someone of liberty: kidnapping, locking someone up (art. 189);
- taking or holding a hostage (art. 252);
- a terrorist offence, or the threat of one (art. 115 § 20);
- causing a disaster that endangers many people: a fire, an explosion, a
  building collapse, a flood (art. 163);
- hijacking a ship, an aircraft or public land transport (art. 166);
- genocide, and murder or grievous harm in a mass attack on a population
  (art. 118, 118a);
- war crimes (art. 120–124);
- a coup, or a violent attempt to remove a constitutional body (art. 127,
  128);
- spying for a foreign intelligence service (art. 130);
- an attempt on the life of the President (art. 134);
- a violent attack on the armed forces to weaken Poland's defence
  (art. 140).

Not on that list, but still escalate under DSA Art. 18 when someone's safety
is at stake: child sexual abuse material (art. 202), grooming a child under
15 online (art. 200a), and threats to kill or harm (art. 190).

## Who to call

| Situation                                     | Contact                                                                                                          |
| --------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| Danger now, or about to happen                | **112**                                                                                                          |
| Crime suspected, no immediate danger          | The nearest police unit (komisariat or komenda), by phone or in person, or any prosecutor's office (prokuratura) |
| Child sexual abuse material                   | **Dyżurnet.pl** (run by NASK), **and** the police                                                                |
| The person's country is unknown or not Poland | Polish police or prosecutor: we are established in Poland                                                        |

Useful Polish phrases:

- "Chcę zgłosić podejrzenie popełnienia przestępstwa." (I want to report a
  suspected crime.)
- A written report to the prosecutor is a "zawiadomienie o podejrzeniu
  popełnienia przestępstwa".

At the end of every call, ask for the case number (sygnatura sprawy) and
the name and unit of the person you spoke to.

## Preserve the evidence

Do this before you hide or remove anything. Three things disappear on their
own, so they come first:

- the author can delete their own encounter, and that deletes the row with
  its RSVPs;
- Coolify's container logs vanish when the app is redeployed;
- Cloudflare and Auth0 keep per-request and login data only for a short
  time.

**Never download, screenshot or copy child sexual abuse material.** Holding
or passing it on is a crime in itself (art. 202). Record only the URL, the
record ids and the account, and let Dyżurnet and the police collect it.

### 1. What you can see

1. Copy the full URL and note the UTC time you found it.
2. Save the page (Ctrl+S, "Webpage, complete") and take a full screenshot
   with the address bar and the clock visible.
3. Keep the report or message that led you there.

### 2. Freeze deploys

Tell the developers to deploy nothing until the logs are saved. Ask in the
team channel without describing the content: "Hold deploys, incident in
progress."

### 3. Database records

Production runs PostgreSQL. The escalation contact can read the rows in
Django admin (`/admin/`, staff account) or export them from a shell in the
app container (Coolify → the ludamus application → Terminal):

```bash
mise run dj dumpdata db_main.Encounter --pks 42 --indent 2
mise run dj dumpdata db_main.User --pks 1234 --indent 2
```

Take a full database backup as well (`pg_dump`) and keep it off the server.

| Data                                  | Table                 | Notes                                                                                             |
| ------------------------------------- | --------------------- | ------------------------------------------------------------------------------------------------- |
| Account                               | `user`                | username, name, email, Discord name, `date_joined`, `last_login`                                  |
| Session or proposal text, cover image | `session`             | Deleting in the panel is soft: the row stays with `deleted_at` set                                |
| Edit history of a session             | `content_change_log`  | who changed what, and when                                                                        |
| Encounter (title, description, place) | `encounter`           | The creator can delete it for good                                                                |
| Encounter sign-ups                    | `encounter_rsvp`      | `ip_address` and time of each sign-up: the only client IP the database stores                     |
| Encounter invitations by email        | `encounter_invitee`   | A daily job (03:40 UTC) purges old rows; export them first if they matter                         |
| Session sign-ups                      | `session_participant` | who joined which session                                                                          |
| Announcements                         | `announcement`        | sphere-wide posts by organizers                                                                   |
| Uploaded images                       | media storage         | Google Cloud Storage or the server's media folder, path in the `cover_image`/`header_image` field |

### 4. IP addresses and request logs

Production sits behind Cloudflare, so the app's own logs record Cloudflare's
address, not the user's. See [DEPLOYMENT.md](DEPLOYMENT.md) (Cloudflare in
front) and [agents/troubleshooting.md](agents/troubleshooting.md) for access.

1. **Cloudflare** holds the real client IP of each request. Query by
   hostname, the path of the content, and a narrow UTC window; save the Ray
   IDs, IPs, times and user agents. Do this first: retention is short.
2. **Auth0** logs every sign-in with its IP address. Open the tenant's logs,
   filter by the user, and export them. Retention is short as well.
3. **Coolify** app logs carry gunicorn access lines: time, method, path,
   status, user agent. Save the lines around the time of the post, before any
   deploy.
4. **PostHog** (project 251811) has events and session recordings only for
   visitors who accepted analytics. Save the matching person, events and
   recordings, if any exist.

### 5. Keep it safe

Put the exports, screenshots and log extracts in one folder that only the
escalation contact can open. Do not paste them into GitHub, Slack, Discord or
email. They go to the police and to nobody else.

> **TODO (#1568): where the evidence folder and the incident record live is
> not decided yet**, nor whether the app needs a "preserve" flag on accounts.
> Until then nothing in the app stops a deletion: the steps above are the
> hold.

## Then deal with the content

After the evidence is safe, stop further harm without destroying anything:

- a session or proposal: delete it in the panel (a soft delete; the row
  stays);
- an account: untick **active** on the user in Django admin. Never delete the
  account: that deletes everything it owns;
- an encounter: the only delete is permanent, so export it first and note
  the export in the record.

## What not to do

- Don't contact the suspect, and don't tell them you reported them.
- Don't forward the material to anyone except the police, the prosecutor and
  Dyżurnet: not to colleagues, not to the person who reported it.
- Don't delete the content, the account or any log.
- Don't deploy until the logs are saved.
- Don't investigate on your own: no tracing IPs, no contacting the victim
  beyond telling them to call 112 if they are in danger.
- Don't promise the reporter an outcome. "We have passed this to the
  authorities" is enough, and only once you have.

## The record

Keep one record per case, next to the evidence. Fill it in as you go.

```text
Case opened (UTC):
Found by:
How it came in (report, message, own discovery):
What (URLs, record ids, account ids):
Why it meets the threshold (DSA Art. 18 / art. 240 item):

Calls and reports:
  - time (UTC), who called, number or office, person and unit spoken to,
    case number, what they asked us to do

Evidence preserved:
  - what, from where, when, stored where

Actions on the content and the account:
  - what, by whom, when

Follow-up (requests from the police, data handed over and when):
```

Close the case only when the police have what they asked for. Tell the
escalation contact and the backup when it is closed.
