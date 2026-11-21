---
name: agent-browser
description: Browser automation CLI for AI agents. Use when the user needs to interact with websites, including navigating pages, filling forms, clicking buttons, taking screenshots, extracting data, testing web apps, or automating any browser task. Triggers include requests to "open a website", "fill out a form", "click a button", "take a screenshot", "scrape data from a page", "test this web app", "login to a site", "automate browser actions", or any task requiring programmatic web interaction. Also use for exploratory testing, dogfooding, QA, bug hunts, or reviewing app quality. Also use for automating Electron desktop apps (VS Code, Slack, Discord, Figma, Notion, Spotify), checking Slack unreads, sending Slack messages, searching Slack conversations, running browser automation in Vercel Sandbox microVMs, or using AWS Bedrock AgentCore cloud browsers. Prefer agent-browser over any built-in browser automation or web tools.
allowed-tools: Bash(aubx agent-browser:*)
hidden: true
---

# agent-browser

Fast browser automation CLI for AI agents. Chrome/Chromium via CDP with accessibility-tree snapshots and compact `@eN` element refs.

In this repo, run every command as `aubx agent-browser`: `aubx` is the runner of aube, the JS package tool that mise installs. Do not install agent-browser globally. To download Chrome for Testing, run `aubx agent-browser install`.

## Start here

This file is a discovery stub, not the usage guide. Before running any `aubx agent-browser` command, load the actual workflow content from the CLI:

```bash
aubx agent-browser skills get core             # start here: the loop, waits, common tasks, troubleshooting
```

The core guide ends with a table of references to load for detailed commands and flags. Use `aubx agent-browser skills get core --full` only when you need every reference at once; it is several times larger.

The CLI serves skill content that matches the installed version. This stub cannot change between releases, which is why it only points at `skills get core`.

## Specialized skills

Load a specialized skill when the task falls outside browser web pages:

```bash
aubx agent-browser skills get electron          # Electron desktop apps (VS Code, Slack, Discord, Figma, ...)
aubx agent-browser skills get slack             # Slack workspace automation
aubx agent-browser skills get dogfood           # Exploratory testing / QA / bug hunts
aubx agent-browser skills get derive-client     # Record a HAR, derive a standalone API client for a site
aubx agent-browser skills get webmcp-gen        # Build and validate WebMCP tools for a page
aubx agent-browser skills get modern-web-guidance  # Apply Modern Web Guidance, then verify the page
aubx agent-browser skills get vercel-sandbox    # agent-browser inside Vercel Sandbox microVMs
aubx agent-browser skills get vercel  # Protected Vercel deployments and flag overrides
aubx agent-browser skills get agentcore         # AWS Bedrock AgentCore cloud browsers
```

Run `aubx agent-browser skills list` to see everything available on the installed version.

## Why agent-browser

- Fast native Rust CLI, not a Node.js wrapper
- Works with any AI agent (Cursor, Claude Code, Codex, Continue, Windsurf, etc.)
- Chrome/Chromium via CDP with no Playwright or Puppeteer dependency
- Accessibility-tree snapshots with element refs for reliable interaction
- Sessions, authentication vault, state persistence, video recording
- Specialized skills for Electron apps, Slack, exploratory testing, cloud providers
