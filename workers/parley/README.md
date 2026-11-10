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

## Inputs

`.env.schema` declares Parley's inputs, and [varlock][varlock] validates them
before `wrangler dev` or Alchemy starts, failing on a missing one.
`wrangler.json` lists the secret under `secrets.required`, which makes
Wrangler pass only that from the environment into the Worker.

| Input               | Development           | Production |
| ------------------- | --------------------- | ---------- |
| `PARLEY_PUBLIC_KEY` | from .env.development | required   |
| `ROOT_DOMAIN`       | unused                | required   |

Give the values the way varlock takes them: in the process environment, or
in a git-ignored `.env.local` beside the schema. The production inputs
are public (a public key and a domain), so they can also live in a committed
`.env.production`.

In production the Worker serves `parley.<ROOT_DOMAIN>` and keeps each
browser's pass in a `SameSite=Strict` cookie, so it admits only the app and
its sphere subdomains. On `workers.dev`, or for a sphere on a custom domain
of its own, browsers withhold the cookie and every room refuses the socket.

## Local development

`mise run start` runs the Worker beside the app, on `localhost:8787` and,
behind portless, as `parley.<ROOT_DOMAIN>` too. On its own:

```sh
aube run dev   # http://localhost:8787
```

The app's `.env.development` points `PARLEY_AGENT_HOST` at it, and both sign
and check passes with the committed `dev-signing-key.pem`. A Worker on a
local host admits any local origin and sends its cookie as
`SameSite=None; Secure; Partitioned`, so an app on another local port or
hostname still connects.

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
3. Provide `ROOT_DOMAIN` and `PARLEY_PUBLIC_KEY` (see [Inputs](#inputs)).
   The domain's zone must already be in the account; Alchemy creates the DNS
   record and certificate. Derive the key with
   `openssl rsa -in parley-private.pem -pubout`.

Then:

```sh
aube run plan:prod     # preview
aube run deploy:prod   # apply; prints the Worker's url
```

Both run with `PARLEY_ENV=production` and the `prod` stage, the only stage
that deploys as `ludamus-parley`. A preview stage
(`PARLEY_ENV=production aube exec varlock run -- alchemy deploy --stage <name>`)
gets its own Worker and Durable Objects, so it never touches production
rooms. It has no custom domain, so it serves the Worker's API but no browser
sockets; remove it with `alchemy destroy --stage <name>` the same way.

Point the app at the result by giving it `PARLEY_SIGNING_PRIVATE_KEY`, the
private half of the key above. It then talks to `parley.<ROOT_DOMAIN>`.

[alchemy]: https://alchemy.run
[varlock]: https://varlock.dev
