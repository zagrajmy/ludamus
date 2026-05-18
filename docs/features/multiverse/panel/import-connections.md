---
status: in-progress
updated: 2026-05-18
---

# Import connections — sphere CRUD

Sphere managers store named API connection secrets — opaque secret
bytes with a human-readable label. One sphere can hold any number of
connections; one connection can back multiple event-level imports (e.g.
the same Google credential drives user sync and proposal-pull from a
sheet). Per-event binding of a connection to a specific API
implementation lives under
`chronology/panel/import-service-configuration.md`.

## Manage connections from the sphere panel

As a sphere manager, I want to list, create, edit, and delete API
connections on a sphere, so that the sphere has named secrets its
events can reference.

- Sphere panel exposes a `Połączenia importu` subpage scoped to the
  current sphere
- List shows display name and per-row Edit / Delete actions
- Create form: display name + API connection secrets paste field
- Edit form: display name editable inline; API connection secrets
  replaceable through an explicit "replace secrets" toggle (existing
  secrets never round-tripped to the UI)
- Display name is unique within the sphere
- No service type, no validity check at save time — the connection is
  opaque until a port references it

## API connection secrets encrypted at rest

As a sphere manager, I want stored API connection secrets never to be
visible to anyone reading the database directly, so that a leaked DB
dump cannot authenticate as the sphere's identity to any provider.

- Secret bytes live in an encrypted column; plaintext is never
  written
- Edit form shows a "secrets configured" placeholder; only accepts
  new secrets through the explicit replace flow
- Plaintext secrets are never returned in any response body
