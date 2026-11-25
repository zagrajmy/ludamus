// A session modal with a cover pins its close button over the cover, which
// then scrolls away under it. Over the dark cover the button is a bare white
// icon; once the cover has gone it needs its own surface again, or it would
// vanish on the light tab bar that sticks there next. data-over-cover says
// which of the two it is, and the template styles both.

// NOTE: the button's bottom edge, top-2 (8px) + size-11 (44px). rootMargin
// takes only px or %, so it cannot read the Tailwind classes.
const CLOSE_BOTTOM_PX = 52;

export const watchCoverClose = (dialog: HTMLElement): void => {
  const scroller = dialog.querySelector<HTMLElement>("[data-session-scroll]");
  const cover = dialog.querySelector("[data-session-scroll] [data-cover]");
  const close = dialog.querySelector<HTMLElement>("[data-cover-close]");
  if (!scroller || !cover || !close) return;
  // The cover still reaches below the button: the button is on it.
  new IntersectionObserver(
    ([entry]) => close.toggleAttribute("data-over-cover", entry.isIntersecting),
    { root: scroller, rootMargin: `-${CLOSE_BOTTOM_PX}px 0px 0px 0px` },
  ).observe(cover);
};
