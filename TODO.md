# TODO

Tasks are grouped by **type**, not by workflow status. `✅` marks a done task;
`🚧` marks one already in progress.

## Group definitions

- **features** — new functionality the user can see: a new page, option, or
  capability on the product.
- **edits** — refactors and improvements that don't change a feature, but
  improve architecture or performance. Touches production code.
- **chores** — tasks not connected to production code: documentation,
  deployment, CI, repo hygiene, dev tooling, tests, and observability/ops.
- **spikes** — investigation, experiments, trying things that might not work.
- **bugs** — things that don't behave as expected and need fixing.

When in doubt where a task belongs, ask.

```mermaid
---
config:
  kanban:
    ticketBaseUrl: 'https://github.com/zagrajmy/ludamus/issues/#TICKET#'
---
kanban
  features
    [Add FastAPI API for MCP]@{ assigned: 'mcp' }
    [Add blurred image placeholders - progressive blur]@{
      assigned: 'frontend'
    }
    [Door cards - printable room schedules]@{ assigned: 'panel' }
    [Konwencik app sync]@{ assigned: 'panel' }
    [Support Markdown in Session.description]@{
      assigned: 'sessions'
      ticket: 9
    }
    [Event settings - discount tiers, submission periods]@{
      assigned: 'panel'
    }
    [Session hosts list - discount tiers and confirmation workflow]@{
      assigned: 'panel'
    }
    [Change log for timetable history - marketing notifications]@{
      assigned: 'panel'
    }
    [Organizer permissions - by program category]@{ assigned: 'panel' }
    [News/announcements - for event page]@{ assigned: 'panel' }
    [View and edit proposals]@{ assigned: 'user-proposals' }
    [Profile page - current and past proposals with statuses]@{
      assigned: 'user-proposals'
    }
    [Resend old proposal]@{ assigned: 'user-proposals' }
    [Claim imported proposals - link by email confirmation]@{
      assigned: 'user-proposals'
    }
    [🚧 Import connections - sphere CRUD]@{ assigned: 'import' }
    [🚧 Event integration configuration]@{ assigned: 'import' }
    [Email verification]@{ assigned: 'crowd' }
    [Import connections - deletion guard]@{ assigned: 'import' }
    [Create event]@{ assigned: 'panel' }
    [Agenda builder session search]@{ assigned: 'agenda' }
    [Filter spaces in the agenda builder]@{ assigned: 'agenda' }
    [Import proposals]@{ assigned: 'import' }
    [Apply mapping - provision event entities]@{ assigned: 'import' }
    [Import mapping]@{ assigned: 'import' }
    [Proposal review]@{ assigned: 'proposals' }
    [Proposal category ordering]@{ assigned: 'proposals' }
    [✅ Program categories - configurable submission forms]@{
      assigned: 'panel'
    }
    [✅ Proposals management - filterable list and accept/reject]@{
      assigned: 'panel'
    }
    [✅ Timetable builder - drag-and-drop scheduling and conflicts]@{
      assigned: 'panel'
    }

  edits
    [Don't use subdomain names in URLs]@{ assigned: 'refactor' }
    [Extract common view boilerplate]@{ assigned: 'refactor' }
    [Links should be passed only to mills]@{ assigned: 'GLIMPSE' }
    [Split mills/pacts/inits into packages per GLIMPSE layer rules]@{
      assigned: 'GLIMPSE'
    }
    [Split check_proposal_rate_limit into query + command]@{
      assigned: 'GLIMPSE'
    }
    [✅ Drop PersonalDataFieldValue.user FK after 0061 deploys, unify read path]@{
      assigned: 'GLIMPSE'
    }
    [Feature flag system]@{ assigned: 'agent-readiness' }
    [Migrate to HTMX]@{ assigned: 'frontend', ticket: 10 }
    [Venues rework]@{ assigned: 'panel', ticket: 155 }
    [GLIMPSE strangler: adapters → layered tree]@{ assigned: 'GLIMPSE' }
    [UoW → Services: request.di.uow → request.services]@{
      assigned: 'GLIMPSE'
    }
    [Legacy module split: legacy.py → per-subdomain]@{ assigned: 'GLIMPSE' }
    [links/db/django layout - split fat repositories]@{ assigned: 'GLIMPSE' }
    [Panel object-scope authorization - close IDOR holes]@{
      assigned: 'GLIMPSE'
    }
    [Link form field errors to inputs - aria-invalid + aria-describedby]@{
      assigned: 'frontend'
    }
    [Proposal form: migrate hand-rolled category select + facilitator/track
     checkboxes to tessera select/checkbox tags]@{
      assigned: 'frontend'
    }

  chores
    [Expand README.md - description, features, quick start]@{
      assigned: 'pre-launch'
    }
    [Add screenshots/demo to README]@{ assigned: 'pre-launch' }
    [Create CONTRIBUTING.md - dev setup, tests, code style]@{
      assigned: 'pre-launch'
    }
    [Create CODE_OF_CONDUCT.md - Contributor Covenant v2.1]@{
      assigned: 'pre-launch'
    }
    [Create SECURITY.md - vulnerability reporting]@{ assigned: 'pre-launch' }
    [Public docs/ARCHITECTURE.md - human-oriented version]@{
      assigned: 'pre-launch'
    }
    [Auto-generated technical docs]@{ assigned: 'agent-readiness' }
    [Architecture diagrams]@{ assigned: 'agent-readiness' }
    [Review and clean up docs/ directory]@{ assigned: 'pre-launch' }
    [Clean up internal files - gitignore or remove task/plan files]@{
      assigned: 'pre-launch'
    }
    [Changelog - Keep a Changelog format, consider CalVer]@{
      assigned: 'pre-launch'
      ticket: 23
    }
    [AGENTS.md file]@{ assigned: 'agent-readiness' }
    [Claude skills definitions]@{ assigned: 'agent-readiness' }
    [Add gh cli]@{ assigned: 'agent-readiness' }
    [Development container configuration]@{ assigned: 'agent-readiness' }
    [Issue templates - YAML forms, config.yml, disable blank issues]@{
      assigned: 'pre-launch'
    }
    [PR template - checklist, under 40 lines]@{ assigned: 'pre-launch' }
    [CODEOWNERS file]@{ assigned: 'pre-launch' }
    [Enable GitHub Discussions]@{ assigned: 'pre-launch' }
    [Label taxonomy + 3-5 good-first-issue starter issues]@{
      assigned: 'pre-launch'
    }
    [Resolve TODO comments - convert to GitHub issues]@{
      assigned: 'pre-launch'
    }
    [Seed data management command - factory_boy + Faker]@{
      assigned: 'pre-launch'
    }
    [Sphere creation command]@{ assigned: 'management', ticket: 14 }
    [Component Views should be tested only in e2e tests]@{ assigned: 'tests' }
    [Isolated/parallel test execution]@{ assigned: 'agent-readiness' }
    [Test suite duration monitoring]@{ assigned: 'agent-readiness' }
    [Technical debt markers tracking]@{ assigned: 'agent-readiness' }
    [Automated release notes]@{ assigned: 'agent-readiness' }
    [Automated deployment pipelines]@{ assigned: 'agent-readiness' }
    [Real-time deploy impact]@{ assigned: 'agent-readiness' }
    [Request tracing]@{ assigned: 'agent-readiness' }
    [Structured logging]@{ assigned: 'agent-readiness' }
    [Engineering telemetry]@{ assigned: 'agent-readiness' }
    [Sentry with source maps]@{ assigned: 'agent-readiness' }
    [Analytics instrumentation]@{ assigned: 'agent-readiness' }
    [Log sanitization/scrubbing]@{ assigned: 'agent-readiness' }
    [PagerDuty/alert rules]@{ assigned: 'agent-readiness' }
    [Incident response playbooks]@{ assigned: 'agent-readiness' }
    [Errors to actionable issues]@{ assigned: 'agent-readiness' }
    [✅ Test coverage thresholds]@{ assigned: 'agent-readiness' }
    [✅ TypeScript/mypy strict mode]@{ assigned: 'agent-readiness' }
    [✅ Reasonable Cyclomatic Complexity thresholds]@{
      assigned: 'agent-readiness'
    }
    [✅ Dead code detection tooling]@{ assigned: 'agent-readiness' }
    [✅ Duplicate code detection tooling]@{ assigned: 'agent-readiness' }
    [✅ Add project URLs to pyproject.toml]@{ assigned: 'pre-launch' }

  spikes
    [Consider refactoring registration to event sourcing]@{
      assigned: 'refactor'
    }

  bugs
    [Agenda: switch day during assign shows wrong red space]@{
      assigned: 'panel'
    }
    [Panel: sphere managers cannot create events]@{
      assigned: 'panel'
      ticket: 339
    }
    [Opening session edit modal is unpleasant]@{
      assigned: 'panel'
      ticket: 342
    }
    [Space reordering has no keyboard alternative to drag-and-drop]@{
      assigned: 'frontend'
      ticket: 281
    }
    [Theme toggle doesn't sync browser chrome (color-scheme)]@{
      assigned: 'frontend'
    }
```
