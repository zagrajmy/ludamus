---
title: 'Frog --version prints help instead of its installed version'
severity: 'minor'
issue: 'zagrajmy/ludamus#1276'
---

## Expected Behavior

`mise run frog -- --version` prints the installed Frog version.

## Current Behavior

Frog 1.1.0 prints its root help instead, making it hard to confirm that the CLI
matches the version pinned in mise.toml. The installed package.json reports 1.1.0.

## Possible Solution

## Minimal Reproducible Example

Run `mise install npm:frog`, then `mise run frog -- --version`.

## Context

Observed while setting up Frog in this repository on 2026-09-10.
