// Bombadil specification for the enrollment pages: Bombadil clicks and types
// its way through the running app and checks these on every state it reaches.
// The defaults catch 4xx/5xx responses, uncaught exceptions and console errors.
// The property below holds the seat count the enroll page shows to the rule
// formal/enrollment proves about the database: nothing a visitor does takes a
// session past its limit.
import { always, extract, now } from "@antithesishq/bombadil";
import { actions, getFingerprint } from "@antithesishq/bombadil/browser";
import { clickablePoint, inViewport, isVisible } from "@antithesishq/bombadil/browser/dom";

export * from "@antithesishq/bombadil/browser/defaults";

type Capacity = { session: number; enrolled: number; limit: number };

// The seat count a session's enroll page shows (chronology/enroll_select.html),
// found by its visible text, "enrolled/limit"; null anywhere else.
const capacity = extract((state): Capacity | null => {
  const page = /\/session\/(\d+)\/enrollment\/$/.exec(state.window.location.pathname);
  if (!page) return null;
  for (const element of Array.from(state.document.querySelectorAll("body *"))) {
    if (element.children.length > 0) continue;
    const count = /^(\d+)\/(\d+)$/.exec((element.textContent ?? "").trim());
    if (count) {
      return {
        session: Number(page[1]),
        enrolled: Number(count[1]),
        limit: Number(count[2]),
      };
    }
  }
  return null;
});

const within = (seen: Capacity | null): boolean => seen !== null && seen.enrolled <= seen.limit;

// Once a session's page has shown it within its limit, no later visit may show
// it over. A session seeded over its limit (an organizer lowered the limit
// after people enrolled) never satisfies the premise, so it does not trip this.
export const sessionNeverGoesPastItsLimit = always(() => {
  const seen = capacity.current;
  return now(() => within(seen)).implies(
    always(
      () =>
        capacity.current === null ||
        seen === null ||
        capacity.current.session !== seen.session ||
        within(capacity.current),
    ),
  );
});

// Random clicking seldom ticks a member and then submits, so on an enroll page
// the form's own controls are offered as extra actions, found by their
// accessible names: each member's "Include <name>" checkbox and the submit
// button, whose label names what submitting does.
const SUBMIT_LABELS = ["Join this session", "Join the waiting list", "Confirm"];

const enrollControls = extract((state) => {
  if (!/\/session\/\d+\/enrollment\/$/.test(state.window.location.pathname)) {
    return [];
  }
  const members = Array.from(
    state.document.querySelectorAll("input[type=checkbox]:not([disabled])"),
  ).filter((box) => (box.getAttribute("aria-label") ?? "").startsWith("Include "));
  const submits = Array.from(
    state.document.querySelectorAll("button[type=submit]:not([disabled])"),
  ).filter((button) => SUBMIT_LABELS.includes((button.textContent ?? "").trim()));
  return [...members, ...submits]
    .filter((element) => isVisible(state.window, element))
    .map((element) => ({ element, point: clickablePoint(element) }))
    .filter(({ point }) => point !== null && inViewport(state.window, point))
    .map(({ element, point }) => ({ fingerprint: getFingerprint(element), point }));
});

export const fillTheEnrollForm = actions(() =>
  enrollControls.current.map((target) => ({ Click: target })),
);
