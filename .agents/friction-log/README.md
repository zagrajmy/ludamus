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
occurrence; add dated evidence to the existing report when the cause is the
same. Local logging needs no GitHub token and does not publish issues.

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

Imported papercuts retain their original date and wording. Confirmed duplicates
share one report with dated occurrences and source links. Historical
observations are not claims that each failure still reproduces today: uncertain
entries remain until verified resolved. Import metadata links each tracked note
to its original source in Git history. Some legacy notes concern the development
environment; new reports should concern this repository or its dependencies.

## Automation

This repository runs Frog in Action-only mode.
[The workflow](../../.github/workflows/friction-log.yml) uses the repository's
own `GITHUB_TOKEN` to file pending reports as issues, reconcile them against
issue state, and accumulate the result in one `frog/sync` pull request. It runs
on default-branch pushes, issues closing or reopening, a daily schedule, or
manual dispatch. Humans review and merge the pull request; no automatic approval
is configured.

The Frog GitHub App must not be installed on this repository. Frog trusts a
single issue author: the App files as `frog-fm[bot]`, the Action as
`github-actions[bot]`, and each one discards the other's issues, clearing their
links and refiling every entry.

Action-only reports this repository only. Entries carrying `target:` stay
deferred, pull requests get no Frog comment, and reports cannot be filed from a
fork.

Under Settings → Actions → General, enable **Allow GitHub Actions to create and
approve pull requests**, which the workflow needs to open the sync pull request.
GitHub may require a user with write access to approve that pull request's
workflow runs.

`maxPerRun` in [config.json](config.json) caps issues filed per run. Keep it
above the number of pending reports: the Action preserves the existing sync
branch untouched whenever a run defers anything, so a ceiling below the backlog
stops the pull request from ever updating.

The workflow action and CLI version are both pinned; update them deliberately.
Inbound reports from other repositories are disabled. Do not run `publish` or
`sync` during development unless explicitly asked.
