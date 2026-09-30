// Forwards calendar replies (iTIP REPLY) to encounter invites to ludamus.
//
// Invites name `rsvp+<token>@<domain>` as organizer; Email Routing matches
// the `rsvp@` rule (subaddressing on) and hands the mail here. `message.to`
// keeps the token, which the app checks against the reply's attendee.

export default {
  async email(message, env) {
    const response = await fetch(env.WEBHOOK_URL, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.WEBHOOK_SECRET}`,
        "Content-Type": "message/rfc822",
        "X-Envelope-To": message.to,
      },
      body: await new Response(message.raw).arrayBuffer(),
    });
    if (response.status >= 500) {
      // Thrown, not rejected: a server error is ours to fix, not the guest's,
      // so it goes to the Worker logs and the Email Routing activity log.
      throw new Error(`ludamus answered ${response.status}`);
    }
    if (!response.ok) {
      message.setReject(`This address only accepts calendar replies (${response.status}).`);
    }
  },
};
