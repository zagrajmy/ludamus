# parley

Cloudflare Worker behind Parley, the chat. Each room is a SQLite-backed
Durable Object from Cloudflare's `agents` SDK:

- `ParleyOrganizersAgent`, one per sphere, for its chat moderators;
- `ParleyEventAgent`, one per event, and `ParleySessionAgent`, one per
  programme point, for the people taking part;
- `ParleyConversationAgent`, one per direct, group or party conversation,
  whose member list Django pushes;
- `ParleySphereAgent`, one per sphere, which holds no messages: it is the
  sphere's deny-list and its feed of which rooms have news;
- `ParleyInboxAgent`, one per person, the same feed for their conversations,
  and their unread mentions: one still unread ten minutes on goes to the app,
  which decides whether to email it.

Django signs one short-lived capability token for every sphere a person is
in; the Worker checks it against `PARLEY_PUBLIC_KEY` before it lets a
browser into a room. It names the spheres someone moderates, the events
whose chats they may enter, and the programme points they take part in, so
a moderator's token does not grow with their sphere's programme.

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

## Retention

Every message, in every kind of room, is deleted for good a year after it
was written. Each read purges what is due first, so no message is served
past its year however late the alarm runs. A room's alarm sweeps its storage
once the oldest message is due, and then at most daily while any remain; a
room with no messages sets none. A sphere's room activity and read positions,
and a person's inbox, drop entries a year old the same way, so no unread flag
outlives its message, and neither does a mention. Event and session rooms go
sooner on top of that: read-only 48 hours after their event ends, and deleted
whole 30 days after.
Django clears its own copy of a reported message on the same one-year rule.

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

"Deploy to production" and "Deploy to staging" (`.github/workflows/`) deploy
the Worker before the app, through `deploy-parley.yml`, at the commit they
deploy. Alchemy compares the bundled source and settings with its state, so a
deploy that changes nothing in the Worker uploads nothing. Production is the
`prod` stage (`ludamus-parley`), staging the `staging` stage
(`ludamus-parley-staging`); each serves `parley.<ROOT_DOMAIN>` with Durable
Objects of its own. No other workflow deploys it.

Each GitHub Environment (`production-coolify`, `staging`) needs:

| Kind   | Name                         | Value                               |
| ------ | ---------------------------- | ----------------------------------- |
| var    | `ROOT_DOMAIN`                | already there for the app           |
| var    | `PARLEY_PUBLIC_KEY`          | public half of the signing key, PEM |
| secret | `PARLEY_SIGNING_PRIVATE_KEY` | its private half, handed to the app |
| secret | `PARLEY_MENTIONS_SECRET`     | random, shared with the app         |
| secret | `CLOUDFLARE_API_TOKEN`       | Zagrajmy account, see below         |

Until an Environment has `PARLEY_PUBLIC_KEY`, its deploys skip the Worker
and the app ships without it. Give each environment a key pair of its own:

```sh
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out parley-private.pem
openssl rsa -in parley-private.pem -pubout
```

`PARLEY_MENTIONS_SECRET` signs the unread mentions the Worker hands the app
to email about (`openssl rand -hex 32`). Without it the chat runs as before
and mentions send no email.

The token needs, on the Zagrajmy account (`add2b427b034a6073f63a849af7de160`),
Workers Scripts edit and Secrets Store edit, and DNS edit on the
`ROOT_DOMAIN` zone, which must already be in that account; Alchemy creates
the DNS record and certificate. Secrets Store read is not enough: with no
saved credentials, as in CI, Alchemy reads its state store's token through a
preview Worker that binds the secret, and binding a secret takes edit.

### The first deploy, by hand

The first deploy creates Alchemy's state store, a Worker named
`alchemy-state-store` that holds deploy state in a Durable Object, and asks
before doing so. Its token and encryption key go into the account's Secrets
Store, which a plain "Edit Cloudflare Workers" token cannot write. Run it once
from a machine signed in to the account:

```sh
aube exec alchemy profile edit --add Cloudflare
aube run plan:prod       # preview
aube run deploy:prod     # apply; prints the Worker's url
```

with `ROOT_DOMAIN` and `PARLEY_PUBLIC_KEY` given (see [Inputs](#inputs)).
`plan:staging` and `deploy:staging` do the same for staging.

A preview stage
(`PARLEY_ENV=production aube exec varlock run -- alchemy deploy --stage <name>`)
gets its own Worker and Durable Objects, so it never touches an
environment's rooms. It has no custom domain, so it serves the Worker's API
but no browser sockets; remove it with `alchemy destroy --stage <name>` the
same way.

[alchemy]: https://alchemy.run
[varlock]: https://varlock.dev
