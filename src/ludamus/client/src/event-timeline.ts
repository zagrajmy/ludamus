// Hour scrubber for the compact event schedule (big events). The rail on the
// right is a vertical index of hours: tap a marker — or drag along the rail like
// a slider — to jump through the schedule, and the marker for the hour currently
// in view stays highlighted as you scroll. Everything is read from the markup
// session-filters.ts / the Django template already render, so this module owns
// no server coupling.

const ACTIVE_CLASSES = ["text-foreground", "font-bold", "bg-bg-tertiary"];

const initScheduleRail = (rail: HTMLElement): void => {
  // The app-shell scrolls #app-scroll, not the document (see app-scroll.ts), so
  // both the scroll-spy viewport and programmatic scrolling target it.
  const scrollRoot = document.getElementById("app-scroll");

  // Snap the content to whole hours so a tap or drag on the rail lands on a
  // section rather than mid-row. Proximity (not mandatory) keeps the header and
  // filter bar above the list freely scrollable. Set here, not in base.html, so
  // only the compact schedule opts the shared scroller into snapping.
  if (scrollRoot) scrollRoot.style.scrollSnapType = "y proximity";
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
    active?.classList.remove(...ACTIVE_CLASSES);
    active = link;
    active?.classList.add(...ACTIVE_CLASSES);
  };

  const scrollToLink = (link: HTMLAnchorElement, behavior: ScrollBehavior): void => {
    const id = link.getAttribute("href")?.slice(1);
    const target = id ? document.getElementById(id) : null;
    target?.scrollIntoView({ behavior, block: "start" });
    setActive(link);
  };

  for (const link of hourLinks) {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      scrollToLink(link, "smooth");
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

  // Drag-to-scrub: treat the rail like a slider. Pointer capture keeps events
  // flowing to the rail even when the finger strays off it, and we resolve the
  // marker by vertical position so dragging glides smoothly between hours.
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
    if (link && link !== active) scrollToLink(link, "auto");
  };

  rail.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    // Let a real tap on a marker fall through to its click handler (smooth jump);
    // only the press-and-drag gesture scrubs.
    dragging = true;
    rail.setPointerCapture(event.pointerId);
  });
  rail.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    event.preventDefault();
    scrubTo(event.clientY);
  });
  const endDrag = (event: PointerEvent): void => {
    dragging = false;
    if (rail.hasPointerCapture(event.pointerId)) rail.releasePointerCapture(event.pointerId);
  };
  rail.addEventListener("pointerup", endDrag);
  rail.addEventListener("pointercancel", endDrag);
};

const rail = document.querySelector<HTMLElement>(".schedule-rail");
if (rail) initScheduleRail(rail);
