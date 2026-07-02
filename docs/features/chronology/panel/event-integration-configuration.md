---
status: in-progress
updated: 2026-05-24
---

# Event integration configuration

## Viewing & attaching

As an organiser, I want to see the integrations currently attached to an
event, so that I know which external systems the event can speak through.

As an organiser, I want to attach an external-system integration to an
event, so that the event has a configured channel through which pipelines
can speak to that system.

As an organiser, I want to change an existing integration's configuration,
so that I can repoint it without recreating it.

As an organiser, I want to remove an integration from an event, so that
the event stops speaking through a channel that is no longer relevant.

As a Polish-speaking organiser, I want the integration panel in Polish, so
that I can configure channels in my own language.

## Verification

As an organiser, I want to verify that an integration can reach what it
needs, so that I know whether it will work before saving it.

As an organiser using assistive technology, I want the verification
outcome announced rather than shown by colour alone, so that I learn the
result without seeing the screen.

As an organiser, I want a failed verification to tell me what went wrong
and how to fix it, so that I'm not guessing about credentials,
permissions, or missing resources.

As an organiser, I want a failed verification to name the specific
identity or resource I must grant access to, so that I can act on it
instead of decoding a raw upstream error.

As an organiser, I want the system to refuse to save an integration that
has not passed verification, so that broken configurations never reach
the pipeline.

As an organiser, I want the save guard to be impossible to satisfy
without a genuine verification — including by replaying an old result —
so that no one can slip a broken configuration past it by faking a pass.

As an organiser, I want changes that cannot affect connectivity to not
demand fresh verification, so that I can fix a typo without re-testing
everything.

## Naming

As an organiser, I want each integration on an event to have a distinct
name, so that I can tell them apart.

## Auditing

As an operator, I want integration create, change, delete, and
verification attempts recorded, so that I can audit who configured a
channel and diagnose failures.
