---
name: modern-web-guidance
description: Apply Chrome's Modern Web Guidance to frontend code, then verify the built page in a real browser with agent-browser. Use when asked to build or modernize UI with web platform best practices, follow Modern Web Guidance or Baseline guidance, or check that a change fixed layout shift, respects reduced motion or the color scheme, or gives a dialog correct focus and inert behavior. Triggers include "use modern web guidance", "modern web best practices", "fix layout shift", "respect reduced motion", "add dark mode", "build an accessible dialog", and "verify this against the guide".
allowed-tools: Bash(aubx agent-browser:*), Bash(aubx modern-web-guidance:*)
---

# Modern Web Guidance

[Modern Web Guidance](https://developer.chrome.com/docs/modern-web-guidance) is a set of guides from Chrome that describe how to build common UI with current web platform features, including Baseline compatibility data. Its CLI returns guidance and can statically scan source files for legacy patterns. It does not load or run the page, so it cannot tell you whether the result works.

Use Modern Web Guidance to decide what to write and agent-browser to check the built page in Chrome. Finish only after every rule you applied has a browser check with recorded evidence.

## Get the guidance

Search for the task, then retrieve the guides that match. You do not need to install anything. In this repo, run both CLIs through `aubx`, the runner of aube, the JS package tool that mise installs: `aubx modern-web-guidance` and `aubx agent-browser`. Do not use `npx` or a global install.

```bash
aubx modern-web-guidance search "animate a dialog"
# [{"id":"animate-to-from-top-layer","description":"Animate elements such as dialogs, popovers, and tooltips as they're entering/exiting the top layer."}, ...]

aubx modern-web-guidance retrieve "dialog"
aubx modern-web-guidance retrieve "dialog,animate-to-from-top-layer"
aubx modern-web-guidance list
```

`retrieve` accepts one ID or several comma-separated IDs. When the text is larger than 9,500 bytes and standard output is not a file, the CLI saves it to a file in the system temporary directory and prints only its path, for example `Output (12.1 KB, 220 lines) saved to .../mwg-guide-49624-1794420750850.md`. Read that whole file before you write code. To choose the location, redirect the output to a file, which receives the full guide:

```bash
aubx modern-web-guidance retrieve "dialog" > dialog.md
```

To find existing code that a guide would replace, run the static scan on the source directory. It reads files only:

```bash
aubx modern-web-guidance legacy-scan ./src --json
aubx modern-web-guidance legacy-scan ./src --guide dialog
```

The scan has rules for only part of the guidance (33 guides in version 1.0.0), so a result with no findings does not mean the code already follows every guide.

Modern Web Guidance also ships its own agent skill (`aubx modern-web-guidance install`). Installing it is optional and interactive; this workflow only needs `search` and `retrieve`.

Write the code from the guidance instead of pasting guide text into the project. Cite the guide ID in the report so a reviewer can retrieve the same guide.

## Workflow

1. **Retrieve.** Search and retrieve the guides for the task. Write down each rule you intend to apply, with its guide ID.
2. **Baseline.** If you are changing existing UI, run the matching browser check below before you edit, so you have a number or snapshot to compare against.
3. **Apply.** Implement the guidance in the project's code.
4. **Verify.** Serve the built page and run the matching check for every rule. A rule without a browser check stays unverified.
5. **Report.** List each rule with its result and evidence, as described in the report section below.

Use the project's own dev or preview server. The examples use `http://localhost:3000`; replace it with the page you changed.

## Layout shift

Use for guides that reserve space for images, embeds, fonts, or late content (for example `performance`).

```bash
aubx agent-browser vitals http://localhost:3000/products
# url: http://localhost:3000/products
# ttfb: 1.4ms  fcp: 56ms  lcp: 56ms  cls: 0.23  inp: -
aubx agent-browser vitals http://localhost:3000/products --json
```

`vitals` navigates to the URL, waits for the load event and then three more seconds for shifts to settle, and reports metrics for that load. Without a URL it reloads the current tab, so client-side state such as an open dialog is lost. In the JSON output, `data.cls.score` is the total and `data.cls.entries` lists each shift with its `startTime` in milliseconds and `value`. Match the largest entry's time to the code that runs then.

Pass when `cls` is at most 0.1 (the "good" Core Web Vitals threshold). When the change fixes an existing shift, `cls` must also be lower than the baseline. `cls: 0` with an empty `entries` array means the load recorded no shifts. Run the check against the same URL before and after the change.

## Reduced motion

Use for guides that animate UI and respect `prefers-reduced-motion` (for example `motion`, `animate-to-from-top-layer`, `spinner`).

```bash
aubx agent-browser open http://localhost:3000/account
aubx agent-browser set media reduced-motion
aubx agent-browser eval "matchMedia('(prefers-reduced-motion: reduce)').matches"
# true
aubx agent-browser eval "getComputedStyle(document.querySelector('dialog')).transitionDuration"
# "0.1s"
aubx agent-browser set media
aubx agent-browser eval "getComputedStyle(document.querySelector('dialog')).transitionDuration"
# "0.3s"
```

`set media` with no arguments sets both the color scheme and reduced motion back to `no-preference`. Read the same computed property under each preference; replace the selector and property with the element and the CSS the guide changes (`transitionDuration`, `animationName`, `transform`). Pass when the value under reduced motion matches what the guide prescribes. The `animate-to-from-top-layer` guide's CSS keeps a short fade under reduced motion and drops only the scale, so the duration goes from `0.3s` to `0.1s` rather than to `0s`. Identical values under both preferences mean the stylesheet ignores the preference.

Computed styles do not show what the user sees during the transition. Record the interaction under each preference so a person can compare them. Recording requires ffmpeg on `PATH`.

```bash
aubx agent-browser set media reduced-motion
aubx agent-browser record start ./dialog-reduced.webm --fps 60
aubx agent-browser click "#delete-account"
aubx agent-browser wait 500
aubx agent-browser record stop
aubx agent-browser press Escape
aubx agent-browser set media
aubx agent-browser record start ./dialog-default.webm --fps 60
aubx agent-browser click "#delete-account"
aubx agent-browser wait 500
aubx agent-browser record stop
```

Make the `wait` longer than the transition so the recording captures all of it. At 60 fps, a 300ms transition spans about 18 frames.

## Color scheme

Use for guides that support light and dark themes (for example `dark-mode`, `color`).

```bash
aubx agent-browser open http://localhost:3000/account
aubx agent-browser set media dark
aubx agent-browser eval "matchMedia('(prefers-color-scheme: dark)').matches"
# true
aubx agent-browser eval "getComputedStyle(document.body).backgroundColor"
aubx agent-browser eval "getComputedStyle(document.documentElement).colorScheme"
aubx agent-browser screenshot ./account-dark.png
aubx agent-browser set media light
aubx agent-browser eval "getComputedStyle(document.body).backgroundColor"
aubx agent-browser screenshot ./account-light.png
```

Pass when the colors differ between `dark` and `light` and match the guide, for example a `color-scheme` value that lets the browser adapt form controls and scrollbars. Each `set media` call sets both preferences, so `set media dark` alone turns reduced motion off. Use `set media dark reduced-motion` to test both together.

## Dialog focus and inertness

Use for guides about modal dialogs and top-layer UI (for example `dialog`). A modal `<dialog>` opened with `showModal()` makes the rest of the page inert, moves focus into the dialog, closes on `Esc`, and returns focus to the element that opened it.

```bash
aubx agent-browser open http://localhost:3000/account
aubx agent-browser snapshot -i
aubx agent-browser click "#delete-account"
aubx agent-browser snapshot -i
aubx agent-browser eval "document.activeElement.id || document.activeElement.textContent"
aubx agent-browser click "a[href='/settings']"
aubx agent-browser press Escape
aubx agent-browser snapshot -i
aubx agent-browser eval "document.activeElement.id"
```

Check each result against the guide:

- **Inertness.** Inert content is removed from the accessibility tree, so the snapshot taken while the dialog is open lists only the dialog's controls. Background links or buttons in that snapshot mean the page behind is still reachable.
- **Initial focus.** `document.activeElement` is inside the dialog, on the element the design chose (for example the `autofocus` button). Focus left on the trigger or `body` is a failure.
- **Blocked input.** The click on background content fails with an error saying the element is covered by the dialog. A successful click is a failure.
- **Dismissal and focus return.** After `press Escape`, the snapshot lists the page again and `document.activeElement.id` is the trigger's ID.

## Report

Report one row per rule you applied:

| Guide | Rule | Check | Result | Evidence |
| --- | --- | --- | --- | --- |
| `performance` | Images reserve space before load | `vitals` before and after | Pass | CLS 0.23 → 0, `entries` empty |
| `dialog` | Background is inert while open | `snapshot -i` with dialog open | Pass | Snapshot lists only Cancel and Delete |
| `animate-to-from-top-layer` | Motion is reduced on request | Computed `transitionDuration` under both preferences | Fail | `0.3s` under both preferences; the guide's CSS gives `0.1s` under reduced motion |

Quote the actual command output as evidence, and attach recordings and screenshots by path. Mark a rule as unverified, with the reason, when no browser check covers it. Do not report a rule as passing because the code follows the guide.

## Cleanup

```bash
aubx agent-browser set media
aubx agent-browser close
```
