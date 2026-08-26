// Grid tracks are server-rendered, so filtering — which only hides the tiles
// (session-filters.ts) — leaves every emptied hour row holding its 3.5rem and
// every emptied room column its --col-min: three surviving sessions scattered
// across a full-size table the reader has to scroll. Collapse the tracks that
// no longer carry a visible tile, and hide the axis labels, gridlines, and
// column rules that belong to them.
// The track sizes themselves stay in index.css as --row-track / --col-track and
// are named, never copied, here: a track list built from literals would drift
// from the served one, silently and with nothing to catch it.
const COLLAPSED = "room-lanes-collapsed";

const collapseEmptyTracks = (lanes: HTMLElement): void => {
  const rowCount = Number(lanes.dataset.rows);
  const roomCount = Number(lanes.dataset.rooms);
  const tileRows = new Set<number>();
  const liveRows = new Set<number>();
  const liveCols = new Set<number>();

  for (const cell of lanes.querySelectorAll<HTMLElement>(".room-lanes-cell")) {
    const visible = cell.querySelector(".session-wrapper:not([hidden])") !== null;
    cell.hidden = !visible;
    const row = Number(cell.dataset.tileRow);
    for (let offset = 0; offset < Number(cell.dataset.tileSpan); offset += 1) {
      tileRows.add(row + offset);
      if (visible) liveRows.add(row + offset);
    }
    if (visible) liveCols.add(Number(cell.dataset.tileCol));
  }

  // Every day of the event shares this grid, so a filter can empty a whole day
  // and leave its heading sitting directly on the next day's — two headings
  // back to back with nothing between them, which reads as a bug. Take the
  // emptied day's rows with it, blank hours included.
  const dayRows = [...lanes.querySelectorAll<HTMLElement>(".room-lanes-day")].map((day) =>
    Number(day.dataset.laneRow),
  );
  const emptied = new Set<number>();
  for (const [index, first] of dayRows.entries()) {
    const last = (dayRows[index + 1] ?? rowCount + 1) - 1;
    const band = Array.from({ length: last - first + 1 }, (_, offset) => first + offset);
    if (band.some((row) => tileRows.has(row)) && !band.some((row) => liveRows.has(row))) {
      for (const row of band) emptied.add(row);
    }
  }

  // An hour no tile ever covered is a break in the programme, and the server
  // renders it at full height. Collapsing it would leave a cleared filter
  // showing a different schedule than the first load did.
  const rowLives = (row: number): boolean =>
    !emptied.has(row) && (liveRows.has(row) || !tileRows.has(row));

  for (const el of lanes.querySelectorAll<HTMLElement>("[data-lane-row]")) {
    el.classList.toggle(COLLAPSED, !rowLives(Number(el.dataset.laneRow)));
  }
  for (const el of lanes.querySelectorAll<HTMLElement>("[data-lane-col]")) {
    el.classList.toggle(COLLAPSED, !liveCols.has(Number(el.dataset.laneCol)));
  }

  // The parent-space label is printed once, above the first column of its run,
  // so collapsing that column takes the label with it. Reprint it on the first
  // column of the run still standing — by group key, not name, since two
  // branches can carry the same parent name.
  const labelled = new Set<string>();
  for (const cell of lanes.querySelectorAll<HTMLElement>("[data-lane-group]")) {
    const label = cell.querySelector<HTMLElement>("[data-lane-group-label]");
    if (!label) continue;
    const group = cell.dataset.laneGroup ?? "";
    const live = liveCols.has(Number(cell.dataset.laneCol));
    label.classList.toggle("invisible", !live || labelled.has(group));
    if (live) labelled.add(group);
  }

  const columns = ["var(--axis-w)"];
  for (let col = 1; col <= roomCount; col += 1) {
    columns.push(liveCols.has(col) ? "var(--col-track)" : "0");
  }
  for (const grid of lanes.querySelectorAll<HTMLElement>(".room-lanes-grid")) {
    grid.style.gridTemplateColumns = columns.join(" ");
  }
  // The grid's min width is calc(--axis-w + --live-rooms * --col-min); the
  // surviving columns are what it must now fit. --rooms is the server's input
  // and is never written back, so the stylesheet's repeat() keeps a valid count.
  lanes.style.setProperty("--live-rooms", String(liveCols.size));

  const body = lanes.querySelector<HTMLElement>(".room-lanes-body");
  if (body) {
    body.style.gridTemplateRows = Array.from({ length: rowCount }, (_, index) =>
      rowLives(index + 1) ? "var(--row-track)" : "0",
    ).join(" ");
  }
};

// The day heading cannot simply be sticky. It sits inside the body scroller,
// whose overflow-x makes that scroller the nearest scrollport, and a scrollport
// that never scrolls vertically pins a sticky child exactly where it was
// rendered. The header is outside the scroller and does stick to the page, so
// it carries the current day instead and the scroll position decides which day
// that is.
const dayCell = (from: ParentNode, field: string): HTMLElement | null =>
  from.querySelector<HTMLElement>(`[data-day-${field}]`);

const trackCurrentDay = (lanes: HTMLElement, head: HTMLElement): (() => void) | null => {
  const label = head.querySelector<HTMLElement>("[data-room-lanes-day-current]");
  const breaks = [...lanes.querySelectorAll<HTMLElement>(".room-lanes-day")];
  if (!label || breaks.length === 0) return null;

  const fields = ["name", "date"];
  // The first day has no seam of its own, so its name is only ever the one the
  // server rendered here. Keep it to put back when no seam has passed yet.
  const firstDay = fields.map((field) => dayCell(label, field)?.textContent ?? "");

  return () => {
    // The last seam that has passed under the header names the day whose rows
    // the reader is looking at; above the first one, that is still day one.
    const edge = head.getBoundingClientRect().bottom;
    let current: HTMLElement | null = null;
    for (const seam of breaks) {
      if (seam.getBoundingClientRect().top > edge) break;
      current = seam;
    }
    for (const [index, field] of fields.entries()) {
      const target = dayCell(label, field);
      const text = current ? (dayCell(current, field)?.textContent ?? "") : firstDay[index];
      if (target && target.textContent !== text) target.textContent = text;
    }
  };
};

const PAN_READY = "room-lanes-pan-ready";
const PANNING = "room-lanes-panning";

// A drag starting on one of these stays a click (or a text caret), unless
// Space says the whole grid is a map right now.
const isInteractive = (target: EventTarget | null): boolean =>
  target instanceof Element && target.closest("a, button, input, select, textarea, label") !== null;

// Space must keep typing spaces wherever text is being written.
const isEditable = (target: EventTarget | null): boolean =>
  target instanceof HTMLElement &&
  (target.isContentEditable || ["BUTTON", "INPUT", "SELECT", "TEXTAREA"].includes(target.tagName));

// The rooms grid lives inside the schedule region the view tabs swap
// (hx-boost), so every lookup below re-runs against the new markup and the
// previous grid's resize listener goes with it. The flag rides each scroller,
// so the page's other htmx traffic — a session modal loading — is a no-op.
let laneListeners = new AbortController();

const initRoomLanes = (): void => {
  const grids = [...document.querySelectorAll<HTMLElement>("[data-room-lanes-scroll]")];
  // Leaving the Rooms view takes the whole grid with it, and nothing later will
  // abort for us, so drop the resize listener rather than leave it measuring
  // detached scrollers.
  if (grids.length === 0) {
    laneListeners.abort();
    return;
  }
  const scrollers = grids.filter((scroller) => !("lanesBound" in scroller.dataset));
  if (scrollers.length === 0) return;

  laneListeners.abort();
  laneListeners = new AbortController();
  const { signal } = laneListeners;

  const panes = scrollers.map((scroller) => ({
    foot: scroller.parentElement?.querySelector<HTMLElement>("[data-room-lanes-foot]") ?? null,
    head: scroller.parentElement?.querySelector<HTMLElement>("[data-room-lanes-head]") ?? null,
    lanes: scroller.closest<HTMLElement>(".room-lanes"),
    scroller,
  }));

  const measureScrollbars = (): void => {
    for (const { head } of panes) {
      // Only the head needs its scrollbar strip carved out of the fade mask;
      // the body's native scrollbar is hidden (the foot strip stands in) and
      // the foot carries no mask. No floor under the measurement: with overlay
      // scrollbars the head reserves nothing, and a floor would punch an
      // unfaded strip through the room-name text.
      head?.style.setProperty("--room-lanes-sb", `${head.offsetHeight - head.clientHeight}px`);
    }
  };
  measureScrollbars();
  globalThis.addEventListener("resize", measureScrollbars, { signal });

  // Map-style panning: Space over the grid arms a pan from anywhere, even a
  // session tile; without it a drag pans only from the background, so tile
  // links keep their clicks. Bound to the body scroller, not the head/foot
  // strips — Firefox delivers pointer events for native scrollbar drags, and
  // a pan starting there would fight the very handles this view added.
  // Mouse only: touch already pans natively.
  let spaceHeld = false;
  // The whole .room-lanes under the pointer, not just the body scroller: the
  // sticky head overlays the grid's top edge, so a pan routinely parks the
  // pointer there — and an un-guarded Space over it pages the app scroller.
  let hovered: HTMLElement | null = null;
  // Gestures currently between pointerdown and their stop: a drag can carry
  // the pointer clear off the component, and Space must stay swallowed there
  // too, or its auto-repeat pages the scroller ~30×/s while pointermove snaps
  // it back — a runaway the user sees as glitching, fast scrolling.
  let pansLive = 0;
  const paintReady = (): void => {
    for (const { lanes, scroller } of panes) {
      scroller.classList.toggle(PAN_READY, spaceHeld && lanes !== null && lanes === hovered);
    }
  };
  document.addEventListener(
    "keydown",
    (event) => {
      if (event.code !== "Space" || isEditable(event.target)) return;
      // Swallow the default on repeats too — each un-prevented one pages the
      // app scroller down mid-gesture.
      if (hovered || pansLive > 0) event.preventDefault();
      if (event.repeat) return;
      spaceHeld = true;
      paintReady();
    },
    { signal },
  );
  document.addEventListener(
    "keyup",
    (event) => {
      if (event.code !== "Space") return;
      spaceHeld = false;
      paintReady();
    },
    { signal },
  );
  // A window switch swallows the keyup; a stuck spaceHeld would turn the
  // next tile click into a pan.
  globalThis.addEventListener(
    "blur",
    () => {
      spaceHeld = false;
      paintReady();
    },
    { signal },
  );

  for (const { foot, head, lanes, scroller } of panes) {
    scroller.dataset.lanesBound = "";
    // schedule:filtered rides the swapped-in grid too: the listener closes over
    // this instance of .room-lanes, so it goes out with the shared controller
    // instead of collapsing tracks in a detached tree.
    if (lanes) {
      document.addEventListener(
        "schedule:filtered",
        () => {
          collapseEmptyTracks(lanes);
        },
        { signal },
      );
    }
    // The head and foot scroll for real — their scrollbars are the grid's top
    // and bottom handles — so each one writes back through the scroller, whose
    // own handler fans the offset out to the other. No feedback loop:
    // assigning a scrollLeft an element already has fires no scroll event, so
    // the ping-pong stops in one step.
    const handles = [head, foot].filter((handle) => handle !== null);
    scroller.addEventListener(
      "scroll",
      () => {
        for (const handle of handles) handle.scrollLeft = scroller.scrollLeft;
      },
      { passive: true, signal },
    );
    for (const handle of handles) {
      handle.addEventListener(
        "scroll",
        () => {
          scroller.scrollLeft = handle.scrollLeft;
        },
        { passive: true, signal },
      );
    }

    // Vertical pan moves the page scroller — the grid clips its own y-overflow.
    const page = scroller.closest<HTMLElement>(".app-scroll");

    const syncDay = lanes && head ? trackCurrentDay(lanes, head) : null;
    if (syncDay) {
      syncDay();
      let queued = 0;
      const queueDay = (): void => {
        if (queued) return;
        queued = requestAnimationFrame(() => {
          queued = 0;
          syncDay();
        });
      };
      page?.addEventListener("scroll", queueDay, { passive: true, signal });
      globalThis.addEventListener("resize", queueDay, { signal });
    }
    lanes?.addEventListener(
      "pointerenter",
      () => {
        hovered = lanes;
        paintReady();
      },
      { signal },
    );
    lanes?.addEventListener(
      "pointerleave",
      () => {
        if (hovered !== lanes) return;
        hovered = null;
        paintReady();
      },
      { signal },
    );
    // A pan's trailing click must not land on whatever the pointer stops
    // over. Same pattern as the timeline rail's scrub: a real pan arms the
    // swallow, the synthesized click (when any) fires before the timeout, and
    // the timeout keeps a click-less gesture from eating the next real tap.
    // Like the rail, the gesture avoids setPointerCapture and pointerdown
    // preventDefault — the swallow plus the dragstart guard below cover what
    // they would, without cancelling the compat mouse stream.
    let swallowClick = false;
    document.addEventListener(
      "click",
      (click) => {
        if (!swallowClick) return;
        swallowClick = false;
        click.preventDefault();
        click.stopPropagation();
      },
      { capture: true, signal },
    );
    scroller.addEventListener(
      "pointerdown",
      (event) => {
        if (event.pointerType !== "mouse" || event.button !== 0) return;
        if (!spaceHeld && isInteractive(event.target)) return;
        const from = {
          left: scroller.scrollLeft,
          top: page?.scrollTop ?? 0,
          x: event.clientX,
          y: event.clientY,
        };
        let panning = false;
        pansLive += 1;
        const drag = new AbortController();
        // Dragging a link or selected text must pan, not start a native drag
        // — a dragstart also makes Firefox cancel the pointer stream.
        document.addEventListener(
          "dragstart",
          (dragEvent) => {
            dragEvent.preventDefault();
          },
          { signal: drag.signal },
        );
        const stop = (up: PointerEvent): void => {
          if (up.pointerId !== event.pointerId) return;
          pansLive -= 1;
          drag.abort();
          scroller.classList.remove(PANNING);
          if (!panning) return;
          swallowClick = true;
          setTimeout(() => {
            swallowClick = false;
          }, 0);
        };
        // The drag listeners live on the document, so they hear the gesture
        // wherever the pointer roams — no capture needed.
        document.addEventListener(
          "pointermove",
          (move) => {
            if (move.pointerId !== event.pointerId) return;
            // A missed pointerup — window switch or context menu mid-drag —
            // would otherwise leave the gesture panning on button-less hovers.
            if (move.buttons === 0) {
              stop(move);
              return;
            }
            const dx = move.clientX - from.x;
            const dy = move.clientY - from.y;
            // The 4px threshold keeps a plain click from becoming a micro-pan.
            if (!panning && Math.abs(dx) < 4 && Math.abs(dy) < 4) return;
            if (!panning) {
              panning = true;
              scroller.classList.add(PANNING);
              // The pre-threshold pixels may have started a text selection;
              // PANNING's user-select only stops it growing further.
              document.getSelection()?.removeAllRanges();
            }
            scroller.scrollLeft = from.left - dx;
            if (page) page.scrollTop = from.top - dy;
          },
          { signal: drag.signal },
        );
        document.addEventListener("pointerup", stop, { signal: drag.signal });
        document.addEventListener("pointercancel", stop, { signal: drag.signal });
      },
      { signal },
    );
  }
};

initRoomLanes();
document.body.addEventListener("htmx:afterSwap", initRoomLanes);
