---
name: issue-maker
description: >-
  Create or update a GitHub issue for the current repo. Use whenever the user
  asks to file, open, create, write, or raise an issue or ticket, or says
  "make an issue for this" / "put that in the backlog" about work that won't
  be done now. Validates the task against the code, searches for duplicates,
  writes a feature-level description, and applies the right labels.
---

# Issue maker skill

1. Validate the task description against current code.
   - if feature is already implemented according to the task definition, drop it
   - if feature is partially implemented, check progress according to task
     definition and ask which parts are still relevant.
2. Search existing issues by task keywords. Something similar → ask what to do.
3. Draft the description. Updating an existing issue → load it, use as base,
   **on contradictions ask**.
   - Cover what features get added, what bugs fixed, what operations changed.
   - Stay at feature level — this may sit for months and the repo will move.
     Generic terms are fine: "needs a Trello API adapter", "a new view",
     "refactor the enrollment mill".
   - Bullet points, sections, emphasized open questions and decisions.
   - **Ask about conceptual ambiguities**, not implementation details.
4. Create or update the issue in the current project.
5. Label it **backlog** and set issue type to:
   - **feature** — new functionality the user can see: a page, option, or
     capability.
   - **edit** — refactor or improvement to production code, no feature change.
   - **chore** — no production code: docs, deployment, CI, repo hygiene, dev
     tooling, tests, observability.
   - **spike** — investigation or experiment that might not work.
   - **bug** — doesn't behave as expected.
6. Set the issue fields: **effort** and **priority** (ask about priority).
