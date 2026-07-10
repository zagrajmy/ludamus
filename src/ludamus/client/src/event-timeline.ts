// Hour scrubber for the compact event schedule (big events). The rail on the
// right is a vertical index of hours: tap a marker — or drag along the rail like
// a slider — to jump through the schedule, and the marker for the hour currently
// in view stays highlighted as you scroll. Everything is read from the markup
// session-filters.ts / the Django template already render, so this module owns
// no server coupling.

import { playSound } from "./sound";

const initScheduleRail = (rail: HTMLElement): void => {
  // The app-shell scrolls #app-scroll, not the document (see app-scroll.ts), so
  // both the scroll-spy viewport and programmatic scrolling target it.
  const scrollRoot = document.getElementById("app-scroll");

  const hourLinks = [...rail.querySelectorAll<HTMLAnchorElement>(".schedule-rail-hour")];
  if (hourLinks.length === 0) return;

  const linkByHour = new Map<string, HTMLAnchorElement>();
  for (const link of hourLinks) {
    const hour = link.dataset.railHour;
    if (hour && !linkByHour.has(hour)) linkByHour.set(hour, link);
  }

  let active: HTMLAnchorElement | null = null;
  const setActive = (link: HTMLAnchorElement | null): void => {
    if (link === active) return;
    if (active) delete active.dataset.active;
    active = link;
    if (active) active.dataset.active = "";
  };

  const scrollToLink = (link: HTMLAnchorElement): void => {
    const id = link.getAttribute("href")?.slice(1);
    const target = id ? document.getElementById(id) : null;
    target?.scrollIntoView({ behavior: "auto", block: "start" });
    setActive(link);
  };

  for (const link of hourLinks) {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      scrollToLink(link);
    });
  }

  // Scroll-spy: highlight the hour whose section sits at the top of the viewport.
  // The band (top 12%–30%) keeps the active marker pinned to what the reader is
  // actually looking at rather than flipping on the very first pixel of overlap.
  const sections = [
    ...document.querySelectorAll<HTMLElement>(".time-slot-section[data-slot-hour]"),
  ];
  const visible = new Set<HTMLElement>();
  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) visible.add(entry.target as HTMLElement);
        else visible.delete(entry.target as HTMLElement);
      }
      let topmost: HTMLElement | null = null;
      let topY = Number.POSITIVE_INFINITY;
      for (const section of visible) {
        const { top } = section.getBoundingClientRect();
        if (top < topY) {
          topY = top;
          topmost = section;
        }
      }
      const hour = topmost?.dataset.slotHour;
      const link = hour ? linkByHour.get(hour) : undefined;
      if (link) setActive(link);
    },
    { root: scrollRoot, rootMargin: "-12% 0px -70% 0px", threshold: 0 },
  );
  for (const section of sections) observer.observe(section);

  // Drag-to-scrub: treat the rail like a slider. Move/end listeners live on the
  // window so the scrub keeps tracking when the pointer strays off the narrow
  // rail, and the marker resolves by vertical position so dragging glides
  // smoothly between hours.
  let dragging = false;
  const linkAtY = (clientY: number): HTMLAnchorElement | null => {
    let nearest: HTMLAnchorElement | null = null;
    let nearestDistance = Number.POSITIVE_INFINITY;
    for (const link of hourLinks) {
      const rect = link.getBoundingClientRect();
      const center = rect.top + rect.height / 2;
      const distance = Math.abs(center - clientY);
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearest = link;
      }
    }
    return nearest;
  };

  const scrubTo = (clientY: number): void => {
    const link = linkAtY(clientY);
    if (link && link !== active) {
      playSound("ui.progress");
      scrollToLink(link);
    }
  };

  // A press only becomes a scrub after real movement; below the threshold the
  // press stays an ordinary tap and the marker's click handler does the jump.
  const DRAG_THRESHOLD_PX = 6;
  let moved = false;
  let startY = 0;

  rail.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    dragging = true;
    moved = false;
    startY = event.clientY;
  });
  globalThis.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    if (!moved && Math.abs(event.clientY - startY) < DRAG_THRESHOLD_PX) return;
    if (!moved) {
      moved = true;
      rail.classList.add("is-scrubbing");
    }
    scrubTo(event.clientY);
  });
  const endDrag = (): void => {
    if (!dragging) return;
    dragging = false;
    rail.classList.remove("is-scrubbing");
    // The synthesized click (when any) fires before this timeout, so a real
    // drag still gets its trailing click swallowed — but a cancelled scrub
    // can't leave the flag hot and eat the next genuine tap.
    setTimeout(() => {
      moved = false;
    }, 0);
  };
  globalThis.addEventListener("pointerup", endDrag);
  globalThis.addEventListener("pointercancel", endDrag);

  rail.addEventListener(
    "wheel",
    (event) => {
      if (!scrollRoot) return;
      event.preventDefault();
      // Firefox reports line-based deltas for a mouse wheel; scale them to
      // pixels or each notch would nudge the page by a few pixels only.
      const scale = event.deltaMode === WheelEvent.DOM_DELTA_LINE ? 16 : 1;
      scrollRoot.scrollBy({ top: event.deltaY * scale });
    },
    { passive: false },
  );
  // A real drag still synthesizes a trailing click on the marker under the
  // pointer; swallow that one click so it can't jump away from where the
  // scrub landed.
  rail.addEventListener(
    "click",
    (event) => {
      if (!moved) return;
      moved = false;
      event.preventDefault();
      event.stopPropagation();
    },
    { capture: true },
  );
};

const rail = document.querySelector<HTMLElement>(".schedule-rail");
if (rail) initScheduleRail(rail);
