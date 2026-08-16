// Grid tracks are server-rendered, so filtering — which only hides the tiles
// (session-filters.ts) — leaves every emptied hour row holding its 3.5rem and
// every emptied room column its --col-min: three surviving sessions scattered
// across a full-size table the reader has to scroll. Collapse the tracks that
// no longer carry a visible tile, and hide the axis labels, gridlines, and
// column rules that belong to them.
const ROW_TRACK = "minmax(3.5rem, auto)";
const COL_TRACK = "minmax(var(--col-min), 1fr)";

const collapseEmptyTracks = (lanes: HTMLElement, roomCount: number): void => {
  const rowCount = Number(lanes.style.getPropertyValue("--rows"));
  const liveRows = new Set<number>();
  const liveCols = new Set<number>();

  for (const cell of lanes.querySelectorAll<HTMLElement>(".room-lanes-cell")) {
    const visible = cell.querySelector(".session-wrapper:not([hidden])") !== null;
    cell.hidden = !visible;
    if (!visible) continue;
    const row = Number(cell.dataset.tileRow);
    for (let offset = 0; offset < Number(cell.dataset.tileSpan); offset += 1) {
      liveRows.add(row + offset);
    }
    liveCols.add(Number(cell.dataset.tileCol));
  }

  for (const el of lanes.querySelectorAll<HTMLElement>("[data-lane-row]")) {
    el.hidden = !liveRows.has(Number(el.dataset.laneRow));
  }
  for (const el of lanes.querySelectorAll<HTMLElement>("[data-lane-col]")) {
    el.hidden = !liveCols.has(Number(el.dataset.laneCol));
  }

  const columns = ["var(--axis-w)"];
  for (let col = 1; col <= roomCount; col += 1) {
    columns.push(liveCols.has(col) ? COL_TRACK : "0");
  }
  for (const grid of lanes.querySelectorAll<HTMLElement>(".room-lanes-grid")) {
    grid.style.gridTemplateColumns = columns.join(" ");
  }
  // The grid's min width is calc(--axis-w + --rooms * --col-min); the surviving
  // columns are what it must now fit.
  lanes.style.setProperty("--rooms", String(liveCols.size));

  const body = lanes.querySelector<HTMLElement>(".room-lanes-body");
  if (body) {
    body.style.gridTemplateRows = Array.from({ length: rowCount }, (_, index) =>
      liveRows.has(index + 1) ? ROW_TRACK : "0",
    ).join(" ");
  }
};

for (const lanes of document.querySelectorAll<HTMLElement>(".room-lanes")) {
  const roomCount = Number(lanes.style.getPropertyValue("--rooms"));
  document.addEventListener("schedule:filtered", () => {
    collapseEmptyTracks(lanes, roomCount);
  });
}

const scrollers = document.querySelectorAll<HTMLElement>("[data-room-lanes-scroll]");

const measureScrollbars = (): void => {
  for (const scroller of scrollers) {
    const reserved = scroller.offsetHeight - scroller.clientHeight;
    scroller.style.setProperty("--room-lanes-sb", `${Math.max(reserved, 14)}px`);
  }
};
measureScrollbars();
globalThis.addEventListener("resize", measureScrollbars);

for (const scroller of scrollers) {
  const head = scroller.parentElement?.querySelector<HTMLElement>("[data-room-lanes-head]");
  if (!head) continue;
  scroller.addEventListener(
    "scroll",
    () => {
      head.scrollLeft = scroller.scrollLeft;
    },
    { passive: true },
  );
}
