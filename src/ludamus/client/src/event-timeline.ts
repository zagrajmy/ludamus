// Hour scrubber for the compact event schedule (big events). The rail on the
// right is a vertical index of hours: tap a marker — or drag along the rail like
// a slider — to jump through the schedule, and the marker for the hour currently
// in view stays highlighted as you scroll. Everything is read from the markup
// session-filters.ts / the Django template already render, so this module owns
// no server coupling.

import { play } from "cuelume";

const hourHasVisibleSection = (hour: string): boolean =>
  [
    ...document.querySelectorAll<HTMLElement>(
      `.time-slot-section[data-slot-hour="${CSS.escape(hour)}"]`,
    ),
  ].some((section) => section.style.display !== "none");

const initScheduleRail = (rail: HTMLElement): void => {
  // The app-shell scrolls #app-scroll, not the document (see app-scroll.ts), so
  // both the scroll-spy viewport and programmatic scrolling target it.
  const scrollRoot = document.getElementById("app-scroll");

  const hourLinks = [...rail.querySelectorAll<HTMLAnchorElement>(".schedule-rail-hour")];
  if (hourLinks.length === 0) return;

  let active: HTMLAnchorElement | null = null;
  const setActive = (link: HTMLAnchorElement | null): void => {
    if (link === active) return;
    if (active) delete active.dataset.active;
    active = link;
    if (active) active.dataset.active = "";
  };

  // The rail owns its markers' visibility — nothing else may touch their
  // display. Two policies compose here: markers whose every section is
  // filtered out disappear (session-filters.ts announces changes via the
  // schedule:filtered event), and because the rail doubles as the phone's
  // scrollbar it must never outgrow the screen, so the remaining markers thin
  // to every 2nd/3rd/… hour per day until they fit. Hidden hours keep working
  // for the scroll-spy by mapping to the nearest visible marker above them.
  let visibleLinks = hourLinks;
  const linkByHour = new Map<string, HTMLAnchorElement>();

  const showEveryNth = (step: number, candidates: ReadonlySet<HTMLElement>): void => {
    let indexInDay = -1;
    let dayLabel: HTMLElement | null = null;
    let dayHasHours = false;
    const closeDay = (): void => {
      if (dayLabel) dayLabel.style.display = dayHasHours ? "" : "none";
    };
    for (const child of rail.children) {
      if (!(child instanceof HTMLElement)) continue;
      if (child.classList.contains("schedule-rail-hour")) {
        if (!candidates.has(child)) {
          child.style.display = "none";
          continue;
        }
        indexInDay += 1;
        const shown = indexInDay % step === 0;
        child.style.display = shown ? "" : "none";
        if (shown) dayHasHours = true;
      } else {
        closeDay();
        dayLabel = child;
        dayHasHours = false;
        indexInDay = -1;
      }
    }
    closeDay();
  };

  const fitRail = (): void => {
    const candidates = new Set<HTMLElement>(
      hourLinks.filter((link) => {
        const hour = link.dataset.railHour;
        return hour !== undefined && hourHasVisibleSection(hour);
      }),
    );
    let step = 1;
    showEveryNth(step, candidates);
    while (rail.scrollHeight > rail.clientHeight && step < hourLinks.length) {
      step += 1;
      showEveryNth(step, candidates);
    }
    const visible = new Set(hourLinks.filter((link) => link.style.display !== "none"));
    visibleLinks = [...visible];
    linkByHour.clear();
    let nearest: HTMLAnchorElement | undefined = visibleLinks[0];
    for (const link of hourLinks) {
      if (visible.has(link)) nearest = link;
      const hour = link.dataset.railHour;
      if (hour && nearest) linkByHour.set(hour, nearest);
    }
    if (active && !visible.has(active)) {
      const hour = active.dataset.railHour;
      setActive((hour ? linkByHour.get(hour) : undefined) ?? null);
    }
  };
  fitRail();
  globalThis.addEventListener("resize", fitRail);
  document.addEventListener("schedule:filtered", fitRail);

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
    for (const link of visibleLinks) {
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
      play("tick");
      scrollToLink(link);
    }
  };

  // A press only becomes a scrub after real movement; below the threshold the
  // press stays an ordinary tap and the marker's click handler does the jump.
  const DRAG_THRESHOLD_PX = 6;
  let moved = false;
  let startY = 0;
  // The scrub belongs to the pointer that started it — a second finger
  // resting elsewhere must not move it, end it, or steal it.
  let scrubPointerId: number | null = null;

  rail.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    if (dragging) return;
    dragging = true;
    moved = false;
    startY = event.clientY;
    scrubPointerId = event.pointerId;
  });
  globalThis.addEventListener("pointermove", (event) => {
    if (!dragging || event.pointerId !== scrubPointerId) return;
    if (!moved && Math.abs(event.clientY - startY) < DRAG_THRESHOLD_PX) return;
    if (!moved) {
      moved = true;
      rail.classList.add("is-scrubbing");
    }
    scrubTo(event.clientY);
  });
  const endDrag = (event: PointerEvent): void => {
    if (!dragging || event.pointerId !== scrubPointerId) return;
    dragging = false;
    scrubPointerId = null;
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
