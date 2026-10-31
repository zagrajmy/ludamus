---
title: 'agent-browser --state resets the session page on every command'
severity: 'minor'
---

## Expected Behavior

`agent-browser --session S --state persona.json <cmd>` loads the persona once and keeps the open page across commands.

## Current Behavior

Passing `--state` on each call relaunched the browser: `open` succeeded, the next `get url` printed `about:blank` and `cookies get` was empty. control-ludamus now closes the session and loads cookies once with `cookies set` instead.

## Possible Solution

## Minimal Reproducible Example

`aubx agent-browser --session s --state st.json open http://localhost:PORT/` then `aubx agent-browser --session s --state st.json get url` → `about:blank`.

## Context

Seen with agent-browser 0.39.0 while rebuilding the verify-ludamus skill.
