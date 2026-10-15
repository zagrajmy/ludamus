# parley

Cloudflare Worker behind Parley, the sphere and session chat. Each room is a
SQLite-backed Durable Object from Cloudflare's `agents` SDK: one
`ParleySphereAgent` per sphere, one `ParleySessionAgent` per programme point.
Django signs a short-lived capability token; the Worker checks it against
`PARLEY_PUBLIC_KEY` before it lets a browser into a room.

## Two configurations, one runtime

- `wrangler.json` describes the Worker's runtime: its compatibility date,
  Durable Object classes and plain vars. `wrangler dev` and the Vitest pool
  read it.
- `alchemy.run.ts` deploys that same runtime with [Alchemy][alchemy]. It reads
  `wrangler.json` and adds only what a deploy needs: the Worker's name, its
  secrets, and Workers Issues.

Never deploy with `wrangler deploy`. It keeps no state, so it would fork the
Worker away from the stack, and its upload omits Issues, which turns
Issues off.

## Local development

```sh
cp .dev.vars.example .dev.vars   # then fill both values
aube run dev                     # http://localhost:8787
```

Set `PARLEY_AGENT_HOST=localhost:8787` in the app's `.env.local`.

## Deploy

One-time setup:

1. Sign in to the Zagrajmy Cloudflare account (`add2b427b034a6073f63a849af7de160`):

   ```sh
   aube exec alchemy profile edit --add Cloudflare
   ```

2. The first deploy creates Alchemy's state store, a Worker named
   `alchemy-state-store` that holds deploy state in a Durable Object, and
   asks before doing so. Its token and encryption key go into the account's
   Secrets Store, which a plain "Edit Cloudflare Workers" token cannot write.
3. Put the deploy inputs in `workers/parley/.env` (git-ignored):

   ```sh
   PARLEY_ALLOWED_ORIGINS="https://zagrajmy.net,https://<each sphere domain>"
   PARLEY_PUBLIC_KEY="<public half of the app's PARLEY_SIGNING_PRIVATE_KEY>"
   ```

   Derive the public key with
   `openssl rsa -in parley-private.pem -pubout`. `PARLEY_INTERNAL_SECRET`,
   which the session rooms use to reach the sphere room, is generated on the
   first deploy and kept in the state store.

Then:

```sh
aube run plan -- --stage prod     # preview
aube run deploy -- --stage prod   # apply; prints the Worker's url
```

Only the `prod` stage deploys as `ludamus-parley`. Any other stage gets its
own Worker and its own Durable Objects, so a preview never touches production
rooms. Remove one with `aube exec alchemy destroy --stage <stage>`.

Point the app at the result: `PARLEY_AGENT_HOST` is the `url` output without
its scheme, and `PARLEY_SIGNING_PRIVATE_KEY` is the private half of the key
above.

[alchemy]: https://alchemy.run
