---
title: 'Playwright''s synthesized Chromium touch scroll never scrolls a combobox list'
severity: 'minor'
---

## Expected Behavior

`Input.synthesizeScrollGesture` with `gestureSourceType: "touch"` over an open combobox list scrolls it, firing pointercancel the way a real swipe does, so an e2e test can reproduce a swipe through the list.

## Current Behavior

Sent the gesture over an option of the open Host list (scrollHeight 2592, clientHeight 216) in the chromium project with an iPhone viewport. The page saw pointerdown, eight pointermoves and a pointerup on the same option, no touchmove, no pointercancel, and the scroller's scrollTop stayed 0. The pointerup landed on the option it started from (touch pointers are implicitly captured), so a handler that picks on pointerup without a movement guard treats the gesture as a tap.

## Possible Solution

Drive the pointer sequence with `locator.dispatchEvent` (pointerdown, pointermove past the slop, pointerup; or pointerdown, pointercancel) and assert on the outcome. Real swipe coverage on a device belongs in scripts/ios-regressions.

## Minimal Reproducible Example

Open `/event/kapitularz-2025-anonymized/`, tap Filters, tap the Host combobox, take the first option's bounding box, then `client.send("Input.synthesizeScrollGesture", { x, y, yDistance: -80, gestureSourceType: "touch" })` and read the scroller's scrollTop.

## Context

Cost two e2e rounds while writing the regression test for the multiselect touch-scroll bug in tests/e2e/tests/event-multiselect.webkit.spec.ts. A related gotcha found the same way: in WebKit, `preventDefault()` on a touch pointerdown suppresses the click that would follow, while Chromium and Firefox still fire it.
