# encounter-replies

Cloudflare Email Worker that keeps encounter RSVPs in sync with guests'
calendars. When someone accepts or declines an encounter invite in Gmail,
Outlook or Apple Calendar, their client mails an iTIP REPLY to the invite's
organizer address, `rsvp+<token>@zagrajmy.net`. Email Routing hands that
mail to this Worker, which posts it raw to
`/encounters/calendar-replies`. The app checks the token, then signs the
guest up or removes them.

## Deploy

1. Email Routing must be on for `zagrajmy.net` (Compute > Email Service >
   Email Routing), which needs Cloudflare DNS and its MX records. If the
   apex domain already receives mail elsewhere, onboard a subdomain instead
   (for example `reply.zagrajmy.net`) and use it in both places below.
2. Turn on **Subaddressing** in Email Routing > Settings.
3. Pick a long random secret and set it on both sides:

   ```sh
   cd cloudflare/encounter-replies
   npx wrangler secret put WEBHOOK_SECRET
   ```

   In the app environment: `ENCOUNTER_REPLY_WEBHOOK_SECRET=<same value>` and
   `ENCOUNTER_REPLY_EMAIL=rsvp@zagrajmy.net`.
4. `npx wrangler deploy`. The `addresses` entry in `wrangler.toml` creates
   the `rsvp@zagrajmy.net` routing rule pointing at the Worker.

Until `ENCOUNTER_REPLY_EMAIL` is set, invites ask for no reply and name
`DEFAULT_FROM_EMAIL` as organizer, so nothing is sent to this address.

## Responses

The app answers 200 for a reply it applied or ignored, 403 for a token that
does not match the attendee, 404 for an unknown encounter, and 422 for mail
that holds no calendar reply. The Worker bounces those 4xx answers back to
the sender and throws on 5xx, which lands in the Worker logs and the Email
Routing activity log rather than in the guest's inbox.
