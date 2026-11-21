# apps/infra — the deployment sketch

rat-stack deploys an app and its cloud as one typed program with [Alchemy](https://alchemy.run): `apps/infra/alchemy.run.ts` declares the Cloudflare resources, and `pnpm infra:plan` / `pnpm infra:deploy` apply them.

This experiment runs its Playwright acceptance suite against a Node host on `localhost:8000` next to a SQLite file (PLAN.md, D3), so nothing here is executed or type-checked: there is no `package.json`, the Alchemy packages are not installed, and the stack below is the shape a deployment would take, not a tested one.

What it would declare, mirroring the template's `apps/web/src/website.ts` and `packages/database/src/hyperdrive-postgres.ts`:

- `Cloudflare.Website.Foldkit` for `apps/web` (the same `dist/server/fetch.js` the Node host loads), with `runWorkerFirst` for `/rpc`, `/api/*`, `/mcp`.
- A Worker for the capability projections (`/rpc`, `/api`, `/mcp`), bound to the website as `BACKEND`.
- `Cloudflare.Hyperdrive` in front of the existing Postgres, because decision D2 keeps Django's schema and data; D1 would only fit after a data migration.
- Secrets through Alchemy's profile, never in `Flags` or the page.

The open question a deployment spike would answer: the Django session bridge needs the shared `SECRET_KEY` on the Worker, and `node:crypto`/`node:zlib` would move to `nodejs_compat` or Web Crypto plus a zlib shim.
