---
title: 'Random proposal-window fixtures flake across the DST fold'
severity: 'minor'
issue: 'zagrajmy/ludamus#1520'
---

## Expected Behavior

Wizard integration tests should compare equivalent persisted event timestamps reliably.

## Current Behavior

The Python job on PR #1516 failed test_details_clear_survives_cover_delete_failure because its Faker-generated proposal end fell inside the repeated Europe/Warsaw hour on 2026-10-25. The expected DTO retained local 02:35 with fold=1, while the database-backed response carried equivalent 01:35 UTC; Python considers these ambiguous-zone datetime values unequal.

## Possible Solution

Reload the event after saving the proposal window so expected DTOs use the persisted UTC representation.

## Minimal Reproducible Example

Compare datetime(2026, 10, 25, 2, 35, tzinfo=ZoneInfo("Europe/Warsaw"), fold=1) with its astimezone(UTC) value. They denote the same instant but compare unequal. CI evidence: https://github.com/zagrajmy/ludamus/actions/runs/38790097935/job/116612121845.

## Context

Unrelated fixture flake encountered while gating the landing-page PR on green CI. All 126 proposal-wizard integration tests pass after reloading the saved fixture.
