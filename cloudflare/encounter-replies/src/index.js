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
    // A server error or a rejected secret (401) or closed webhook (404) is
    // ours to fix, not the guest's: thrown, it lands in the Worker logs and
    // the Email Routing activity log instead of bouncing to them.
    if (response.status >= 500 || response.status === 401 || response.status === 404) {
      throw new Error(`ludamus answered ${response.status}`);
    }
    if (response.status === 403) {
      message.setReject(
        "We could not match this reply to the invite it answers. Reply from the " +
          "address the invite was sent to, or answer on the encounter page.",
      );
    } else if (!response.ok) {
      message.setReject(`This address only accepts calendar replies (${response.status}).`);
    }
  },
};
