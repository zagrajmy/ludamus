---
status: draft
updated: 2026-05-22
---

# Email verification

## Verifying

As a user, I want to verify ownership of a new email address, so that
the system trusts I own it.

As a user, I want to request a fresh verification link, so that I can
recover when a previous one is lost or expired.

As a user, I want an expired or unknown verification link to explain
itself and offer a way forward, so that I am not stuck on a dead page.

As a user signing in through an external identity provider, I want my
email accepted as verified when the provider has already verified it,
so that I am not asked to redo work.

## Changing an address safely

As a user, I want changing my email to require proof of the new address
before the change takes effect, so that nobody can hijack my account by
typing in their address.

As a user, I want my pending new address to be unclaimable by anyone
else while I am verifying it, so that my change cannot race with a
fresh signup.

As a user, I want the old address notified of a pending change, so that
I can intervene if I did not request it.

As a user, I want to cancel a pending email change without logging in,
so that I can stop a hijack even if I have lost access to the account.

As a user, I want a confirmation to the old address once the change
completes, so that I know the move actually finished.

## Living with unverified state

As a user, I want a soft reminder while my email is unverified, so that
I do not forget to finish verifying.

As a user, I want to dismiss the unverified-email reminder for a while,
so that it does not pester me on every page.

As a user, I want the system to remain usable while my email is
unverified, so that I am not blocked from real work over an
administrative gap.

## Bulk operations

As an operator, I want a way to dispatch verification reminders in bulk,
so that I can nudge a backlog of unverified users in one motion.

As an operator, I want to see what a bulk verification run would do
before sending, so that I do not spam users by accident.
