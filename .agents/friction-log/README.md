# Friction log

[Frog](https://frog.fm) stores one report per directory, alongside optional
reproduction artifacts. Commit reports with the code that exposed the problem.
There is no shared journal or tracked index.

## Read and record

Frog is pinned in `mise.toml`; `mise install` installs it.

```sh
mise run frog -- list
mise run frog -- log "Short, specific title"
```

For noninteractive logging, pipe a title on the first line, then Markdown
matching the repository's [issue form](../../.github/ISSUE_TEMPLATE/friction.yml):

```sh
mise run frog -- log <<'REPORT'
Describe the failure

## Expected Behavior

What should happen.

## Current Behavior

What you ran and what failed. Required.

## Possible Solution

## Minimal Reproducible Example

Commands or steps; put supporting files in the entry's artifacts/ directory.

## Context

How this affected the work.
REPORT
```

Keep all five headings in order; optional answers may be empty. Do not include
secrets or private transcripts. Read existing reports before recording another
occurrence. Local logging needs no GitHub token and does not publish issues.

## Resolve

After verifying a fix, close its linked issue. For an unpublished report:

```sh
mise run frog -- resolve <id>
```

Commit the resulting deletion. Put lasting guidance in the relevant project
documentation or tooling rather than keeping a resolved report as instructions.

## Validation and migration

`mise run lint:frog` checks that every report parses; it also runs in `lint` and
CI. A malformed report fails validation instead of producing a partial list.

Imported papercuts retain their original date and wording. Historical
observations are not claims that each failure still reproduces today: uncertain
entries remain until verified resolved. Import metadata links each tracked note
to its original source in Git history. Some legacy notes concern the development
environment; new reports should concern this repository or its dependencies.

## Automation

This repository uses the Frog GitHub App, not Action-only mode. The App reports
issues; [the reconciliation workflow](../../.github/workflows/friction-log.yml)
uses OIDC to fetch their state and updates one `frog/sync` PR. It runs on
default-branch pushes, authenticated App signals, a daily schedule, or manual
dispatch. Humans review and merge the PR; no automatic approval is configured.

The App must have access to this repository. Under Settings → Actions → General,
enable **Allow GitHub Actions to create and approve pull requests**: App mode
still uses the workflow token to create the sync PR. GitHub may require a user
with write access to approve that PR's workflow runs.

The workflow action and CLI version are both pinned; update them deliberately.
Inbound reports from other repositories are disabled. Do not run `publish` or
`sync` during development unless explicitly asked.
