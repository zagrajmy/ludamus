---
status: in-progress
updated: 2026-05-22
---

# Import connections — sphere CRUD

## Managing connections

As a sphere manager, I want to list, create, edit, and delete API
connections on a sphere, so that the sphere has named credentials its
events can reference.

As a sphere manager, I want each connection on a sphere to have a
distinct name, so that I can tell them apart in pickers.

## Keeping secrets

As a sphere manager, I want stored credentials to be unreadable to
anyone with raw database access, so that a leaked dump cannot
impersonate the sphere.

As a sphere manager, I want existing credentials never displayed back
to me, so that shoulder-surfing or cached responses cannot expose them.

As a sphere manager, I want replacing credentials to require an explicit
confirmation, so that a casual edit cannot silently overwrite a working
secret.
