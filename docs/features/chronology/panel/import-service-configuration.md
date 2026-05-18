---
status: draft
updated: 2026-05-18
---

# Import service configuration

An event opts into the import pipeline by configuring one or more
**services**. Each service bundles an API implementation (e.g. Google
proposal puller, Google user sync), a reference to a sphere-level API
connection that provides the secret, and a per-implementation JSON
configuration document. Two services on the same event may share one
connection — one Google credential can drive both user sync and
proposal pull — the JSON config is what specialises each.

Sphere-level API connection CRUD:
`multiverse/panel/import-connections.md`. Mapping document:
`import-mapping.md`. Provisioning: `import-apply-mapping.md`. Pull:
`import-pull-proposals.md`.

## Add a service to an event

As an organiser, I want to attach an API implementation, a sphere
connection, and a JSON configuration to an event, so that the event
has a configured port the pipeline can speak through.

- Event panel's "Import / Eksport" → "Źródła" subpage hosts the list
  and "Add service" action
- Add-service form fields: API implementation picker (registry shipped
  with the codebase), display name, sphere connection picker (any
  connection on the sphere), JSON config textarea
- Each API implementation declares a Pydantic class describing its
  config shape; the JSON config textarea is parsed and validated
  through that class on "Validate" and on Save
- Validation errors render inline with the offending JSONPath and a
  one-line explanation per error
- Display name is mandatory and unique within the event
- Save is refused until the most recent "Check service" returned `ok`

## Edit a service

As an organiser, I want to change a service's display name,
connection, or JSON config, so that I can repoint a port without
re-creating it.

- Edit page same shape as create
- Changing the connection or any value in the JSON config invalidates
  the previous check; save is refused until a fresh "Check service"
  returns `ok`
- Changing only display name does not require re-check

## Delete a service

As an organiser, I want to remove a service from an event, so that the
event stops pulling from a port that's no longer relevant.

- Delete confirmation lists the service's display name + API
  implementation + connection
- Delete is allowed at any time; previously-imported sessions remain
  on the event (pipeline is append-only — see pull-proposals)

## Run "Check service"

As an organiser, I want a button that confirms the chosen connection
and JSON config let the API implementation reach what it needs, so
that I know whether the service will work before saving.

- Sticky "Check service" button on the add / edit form
- Check delegates to the picked API implementation; each
  implementation decides what to probe (e.g. Google proposal puller
  checks form + sheet; Google user sync checks Directory API access)
- Each check returns an outcome of `ok`, `auth_failed`, `forbidden`,
  `not_found`, or an implementation-specific code
- Failures include actionable hints — e.g., for `forbidden`, the
  acting identity's email and the resource ID, with a "share with
  this email" prompt
- Result is ephemeral — lives in the click response, never persisted
  on the service record
- Save button enables only when the check returns `ok`

## Invariants surfaced to the organiser

- Connection deletion is blocked at sphere level while any event
  service references that connection (cross-link to
  `multiverse/panel/import-connections-deletion-guard.md`)
- Display name is unique within an event
- Mapping references services by API implementation identifier; when
  two services on the same event share an implementation, the mapping
  disambiguates by display name
