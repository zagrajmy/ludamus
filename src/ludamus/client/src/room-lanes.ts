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

  // An hour no tile ever covered is a break in the programme, and the server
  // renders it at full height. Collapsing it would leave a cleared filter
  // showing a different schedule than the first load did.
  const rowLives = (row: number): boolean => liveRows.has(row) || !tileRows.has(row);

  for (const el of lanes.querySelectorAll<HTMLElement>("[data-lane-row]")) {
    el.classList.toggle(COLLAPSED, !rowLives(Number(el.dataset.laneRow)));
  }
  for (const el of lanes.querySelectorAll<HTMLElement>("[data-lane-col]")) {
    el.classList.toggle(COLLAPSED, !liveCols.has(Number(el.dataset.laneCol)));
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

  const measureScrollbars = (): void => {
    for (const scroller of scrollers) {
      const reserved = scroller.offsetHeight - scroller.clientHeight;
      scroller.style.setProperty("--room-lanes-sb", `${Math.max(reserved, 14)}px`);
    }
  };
  measureScrollbars();
  globalThis.addEventListener("resize", measureScrollbars, { signal });

  for (const scroller of scrollers) {
    scroller.dataset.lanesBound = "";
    // schedule:filtered rides the swapped-in grid too: the listener closes over
    // this instance of .room-lanes, so it goes out with the shared controller
    // instead of collapsing tracks in a detached tree.
    const lanes = scroller.closest<HTMLElement>(".room-lanes");
    if (lanes) {
      document.addEventListener(
        "schedule:filtered",
        () => {
          collapseEmptyTracks(lanes);
        },
        { signal },
      );
    }
    const head = scroller.parentElement?.querySelector<HTMLElement>("[data-room-lanes-head]");
    if (!head) continue;
    scroller.addEventListener(
      "scroll",
      () => {
        head.scrollLeft = scroller.scrollLeft;
      },
      { passive: true, signal },
    );
  }
};

initRoomLanes();
document.body.addEventListener("htmx:afterSwap", initRoomLanes);
