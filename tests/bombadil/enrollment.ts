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

// The capacity pill ("enrolled/limit") on a session's enroll page
// (chronology/enroll_select.html), or null anywhere else.
const capacity = extract((state): Capacity | null => {
  const page = /\/session\/(\d+)\/enrollment\/$/.exec(state.window.location.pathname);
  if (!page) return null;
  for (const pill of Array.from(state.document.querySelectorAll("span.tabular-nums"))) {
    const count = /^(\d+)\/(\d+)$/.exec((pill.textContent ?? "").trim());
    if (count) {
      return { session: Number(page[1]), enrolled: Number(count[1]), limit: Number(count[2]) };
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
// the form's own controls are offered as extra actions: the member checkboxes,
// the guest stepper, and the submit button.
const enrollControls = extract((state) => {
  if (!/\/session\/\d+\/enrollment\/$/.test(state.window.location.pathname)) {
    return [];
  }
  const selector =
    "[data-enroll-row] input[type=checkbox]:not([disabled]), " +
    "form[method=post] button:not([disabled])";
  return Array.from(state.document.querySelectorAll(selector))
    .filter((element) => isVisible(state.window, element))
    .map((element) => ({ element, point: clickablePoint(element) }))
    .filter(({ point }) => point !== null && inViewport(state.window, point))
    .map(({ element, point }) => ({ fingerprint: getFingerprint(element), point }));
});

export const fillTheEnrollForm = actions(() =>
  enrollControls.current.map((target) => ({ Click: target })),
);
