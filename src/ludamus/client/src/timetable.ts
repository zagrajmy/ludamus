import { requestConfirm } from "./confirm";

interface PreferredSlot {
  end: string;
  start: string;
}

interface Placement {
  backUrl: string | null;
  confirmed: boolean;
  duration: number;
  preferredSlots: PreferredSlot[];
  sessionPk: string;
}

// Click-to-place mode (armed via clicking a session or an Assign button).
let armed: Placement | null = null;
// Active drag payload; independent of `armed` so a bare drag also works.
let dragging: Placement | null = null;

declare const htmx: {
  ajax: (method: string, url: string, opts: { swap: string; target: string }) => void;
};

const banner = (): HTMLElement => document.getElementById("assign-mode-banner")!;

const grid = (): HTMLElement => document.getElementById("timetable-grid")!;

const dayGrids = (): NodeListOf<HTMLElement> =>
  document.querySelectorAll<HTMLElement>(".timetable-day-grid");

const columns = (): NodeListOf<HTMLElement> =>
  document.querySelectorAll<HTMLElement>(".timetable-column");

const columnsForDayGrid = (dayGrid: HTMLElement): NodeListOf<HTMLElement> =>
  dayGrid.querySelectorAll<HTMLElement>(".timetable-column");

const dayGridForColumn = (col: HTMLElement): HTMLElement | null =>
  col.closest<HTMLElement>(".timetable-day-grid");

const csrfToken = (): string =>
  (document.querySelector("[name=csrfmiddlewaretoken]") as HTMLInputElement).value;

function pxPerMinute(cal: HTMLElement): number {
  const raw = getComputedStyle(cal).getPropertyValue("--minute-px").trim();
  const parsed = Number.parseFloat(raw);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1;
}

// Display in the event's own UTC offset (parsed from data-event-start), not the
// browser's local timezone -- they can disagree with the grid's own labels.
function eventUtcOffsetMinutes(cal: HTMLElement): number {
  const match = /([+-])(\d{2}):(\d{2})$/.exec(cal.dataset.eventStart ?? "");
  if (!match) return 0;
  const sign = match[1] === "-" ? -1 : 1;
  return sign * (Number(match[2]) * 60 + Number(match[3]));
}

function formatHm(d: Date, utcOffsetMinutes: number): string {
  const shifted = new Date(d.getTime() + utcOffsetMinutes * 60_000);
  return `${String(shifted.getUTCHours()).padStart(2, "0")}:${String(shifted.getUTCMinutes()).padStart(2, "0")}`;
}

const hoverPreview = (): HTMLElement => {
  let el = document.getElementById("timetable-hover-preview");
  if (!el) {
    el = document.createElement("div");
    el.id = "timetable-hover-preview";
    el.className = "timetable-hover-preview hidden";
    document.body.append(el);
  }
  return el;
};

function hideHoverPreview(): void {
  hoverPreview().classList.add("hidden");
}

const dropGuide = (): HTMLElement => {
  let el = document.getElementById("timetable-drop-guide");
  if (!el) {
    el = document.createElement("div");
    el.id = "timetable-drop-guide";
    el.className = "timetable-drop-guide";
  }
  return el;
};

function hideDropGuide(): void {
  document.getElementById("timetable-drop-guide")?.remove();
}

// A ghost block, snapped to the drop time and sized to the session, shown
// inside the hovered column while dragging -- the Google-Calendar drop preview.
function showDropGuide(col: HTMLElement, startDt: Date, placement: Placement): void {
  const cal = dayGridForColumn(col);
  if (!cal?.dataset.eventStart) return;
  const minutePx = pxPerMinute(cal);
  const topPx =
    ((startDt.getTime() - new Date(cal.dataset.eventStart).getTime()) / 60_000) * minutePx;
  const endDt = new Date(startDt.getTime() + placement.duration * 60_000);
  const utcOffsetMinutes = eventUtcOffsetMinutes(cal);

  const guide = dropGuide();
  guide.style.top = `calc(${topPx}px + 20px)`;
  guide.style.height = `${Math.max(20, placement.duration * minutePx)}px`;
  guide.textContent = `${formatHm(startDt, utcOffsetMinutes)} – ${formatHm(endDt, utcOffsetMinutes)}`;
  if (guide.parentElement !== col) col.append(guide);
}

function parsePreferredSlots(raw: string | undefined): PreferredSlot[] {
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (s): s is PreferredSlot =>
        typeof s === "object" &&
        s !== null &&
        typeof (s as PreferredSlot).start === "string" &&
        typeof (s as PreferredSlot).end === "string",
    );
  } catch {
    return [];
  }
}

function clearPreferredSlotOverlays(): void {
  for (const el of document.querySelectorAll<HTMLElement>(".timetable-preferred-slot")) el.remove();
}

function renderPreferredSlotOverlays(): void {
  clearPreferredSlotOverlays();
  const slots = (armed ?? dragging)?.preferredSlots ?? [];
  if (slots.length === 0) return;

  for (const cal of dayGrids()) {
    const { eventStart } = cal.dataset;
    if (!eventStart) continue;

    const totalMinutes = Number(cal.dataset.totalMinutes);
    if (!totalMinutes) continue;

    const eventStartMs = new Date(eventStart).getTime();
    const minutePx = pxPerMinute(cal);
    const pxPerMs = minutePx / 60_000;
    const totalHeightPx = totalMinutes * minutePx;

    for (const slot of slots) {
      const startMs = new Date(slot.start).getTime();
      const endMs = new Date(slot.end).getTime();
      if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) continue;

      const rawTop = (startMs - eventStartMs) * pxPerMs;
      const rawBottom = (endMs - eventStartMs) * pxPerMs;
      const top = Math.max(0, rawTop);
      const bottom = Math.min(totalHeightPx, rawBottom);
      if (bottom <= top) continue;

      for (const col of columnsForDayGrid(cal)) {
        const overlay = document.createElement("div");
        overlay.className = "timetable-preferred-slot";
        overlay.style.top = `calc(${top}px + 20px)`;
        overlay.style.height = `${bottom - top}px`;
        col.append(overlay);
      }
    }
  }
}

function markColumnsActive(active: boolean): void {
  for (const col of columns()) col.classList.toggle("assign-mode-active", active);
}

function enterAssignMode(placement: Placement): void {
  armed = placement;
  banner().classList.remove("hidden");
  markColumnsActive(true);
  renderPreferredSlotOverlays();
}

function exitAssignMode(): void {
  armed = null;
  banner().classList.add("hidden");
  markColumnsActive(false);
  clearPreferredSlotOverlays();
  hideHoverPreview();
}

function placementFromAssignButton(btn: HTMLElement): Placement {
  return {
    backUrl: btn.dataset.assignBackUrl ?? null,
    confirmed: btn.dataset.assignConfirmed === "true",
    duration: Number(btn.dataset.assignDuration) || 60,
    preferredSlots: parsePreferredSlots(btn.dataset.assignPreferredSlots),
    sessionPk: btn.dataset.assignSessionPk!,
  };
}

function placementFromDraggable(el: HTMLElement): Placement {
  const sessionPk = el.dataset.sessionPk!;
  return {
    backUrl: armed?.sessionPk === sessionPk ? armed.backUrl : null,
    confirmed: el.dataset.confirmed === "true",
    duration: Number(el.dataset.duration) || 60,
    preferredSlots: armed?.sessionPk === sessionPk ? armed.preferredSlots : [],
    sessionPk,
  };
}

function startTimeAt(col: HTMLElement, clientY: number): Date | null {
  const cal = dayGridForColumn(col);
  if (!cal) return null;
  const { eventStart } = cal.dataset;
  if (!eventStart) return null;
  const slotMinutes = Number(cal.dataset.slotMinutes);
  const snapMinutes = Number(cal.dataset.snapMinutes) || slotMinutes;
  const pxPerSnap = snapMinutes * pxPerMinute(cal);

  const rect = col.getBoundingClientRect();
  const snapIndex = Math.floor((clientY - rect.top) / pxPerSnap);
  const offsetMinutes = snapIndex * snapMinutes;

  const startDt = new Date(eventStart);
  startDt.setMinutes(startDt.getMinutes() + offsetMinutes);
  return startDt;
}

function postPlacement(
  placement: Placement,
  spacePk: string,
  startDt: Date,
  onFail: () => void,
): void {
  const endDt = new Date(startDt.getTime() + placement.duration * 60_000);
  const body = new FormData();
  body.append("session_pk", placement.sessionPk);
  body.append("space_pk", spacePk);
  body.append("start_time", startDt.toISOString());
  body.append("end_time", endDt.toISOString());
  body.append("csrfmiddlewaretoken", csrfToken());

  fetch(grid().dataset.assignUrl!, { body, method: "POST" })
    .then((resp) => {
      if (resp.ok) {
        document.body.dispatchEvent(new CustomEvent("timetableChanged"));
        if (placement.backUrl) {
          htmx.ajax("GET", placement.backUrl, { swap: "outerHTML", target: "#left-pane" });
        }
      } else {
        alert(`Could not place session (server returned ${resp.status}). ` + `Please try again.`);
        onFail();
      }
    })
    .catch(() => {
      alert("Network error placing session. Please try again.");
      onFail();
    });
}

// Moving a confirmed program item clears its confirmation server-side, so the
// drop is gated behind the shared confirm dialog before anything is sent.
function submitPlacement(placement: Placement, spacePk: string, startDt: Date): void {
  const run = (): void => {
    if (armed?.sessionPk === placement.sessionPk) exitAssignMode();
    postPlacement(placement, spacePk, startDt, () => enterAssignMode(placement));
  };
  if (placement.confirmed) {
    const { confirmMove, confirmMoveAction } = grid().dataset;
    requestConfirm(confirmMove ?? "", confirmMoveAction ?? null, run);
  } else {
    run();
  }
}

// Delegate clicks: Assign buttons arm the mode, an armed grid click places.
document.addEventListener("click", (e) => {
  const target = e.target as Element;

  const assignBtn = target.closest<HTMLElement>("[data-assign-session-pk]");
  if (assignBtn) {
    enterAssignMode(placementFromAssignButton(assignBtn));
    return;
  }

  // A click on a placed session selects it (detail pane + re-arm via
  // htmx:load) — it must never double as a placement click for the
  // previously armed session.
  if (armed && !target.closest(".timetable-session")) {
    const col = target.closest<HTMLElement>(".timetable-column.assign-mode-active");
    if (col) {
      const clientY = e instanceof MouseEvent ? e.clientY : col.getBoundingClientRect().top;
      const startDt = startTimeAt(col, clientY);
      if (startDt) submitPlacement(armed, col.dataset.spacePk!, startDt);
    }
  }
});

// Drag & drop: session cards in the left pane and placed sessions on the grid
// are draggable; dropping on a column places the session at the drop time. A
// ghost guide (showDropGuide) tracks the snapped drop position while dragging.
document.addEventListener("dragstart", (e) => {
  const el = (e.target as Element).closest?.<HTMLElement>('[draggable="true"][data-session-pk]');
  if (!el || !e.dataTransfer) return;
  dragging = placementFromDraggable(el);
  e.dataTransfer.effectAllowed = "move";
  e.dataTransfer.setData("text/plain", dragging.sessionPk);
  markColumnsActive(true);
  renderPreferredSlotOverlays();
});

document.addEventListener("dragover", (e) => {
  if (!dragging) return;
  const col = (e.target as Element).closest?.<HTMLElement>(".timetable-column");
  if (!col) {
    hideDropGuide();
    return;
  }
  e.preventDefault();
  if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
  const startDt = startTimeAt(col, e.clientY);
  if (startDt) showDropGuide(col, startDt, dragging);
});

document.addEventListener("drop", (e) => {
  const col = (e.target as Element).closest?.<HTMLElement>(".timetable-column");
  hideDropGuide();
  if (!dragging || !col) return;
  e.preventDefault();
  const startDt = startTimeAt(col, e.clientY);
  if (startDt) submitPlacement(dragging, col.dataset.spacePk!, startDt);
  dragging = null;
});

document.addEventListener("dragend", () => {
  dragging = null;
  hideDropGuide();
  if (armed) {
    renderPreferredSlotOverlays();
  } else {
    markColumnsActive(false);
    clearPreferredSlotOverlays();
  }
});

// Clicking a session (list card or grid block) loads the detail pane for
// review only — it never arms assign mode. Placement arms solely from an
// explicit Assign/Reassign click (handled by the delegated click listener
// above). Loading any pane cancels a mode armed from a previous session.
document.body.addEventListener("htmx:load", (evt) => {
  const el = (evt as CustomEvent).detail?.elt;
  if (!(el instanceof Element) || el.id !== "left-pane") return;
  exitAssignMode();
});

// Live snapped-time preview near the cursor while in assign mode
document.addEventListener("mousemove", (e) => {
  if (!armed) return;
  const col = (e.target as Element).closest<HTMLElement>(".timetable-column.assign-mode-active");
  if (!col) {
    hideHoverPreview();
    return;
  }

  const cal = dayGridForColumn(col);
  const startDt = cal && startTimeAt(col, e.clientY);
  if (!cal || !startDt) return;
  const endDt = new Date(startDt.getTime() + armed.duration * 60_000);

  const utcOffsetMinutes = eventUtcOffsetMinutes(cal);
  const preview = hoverPreview();
  preview.textContent = `${formatHm(startDt, utcOffsetMinutes)} – ${formatHm(endDt, utcOffsetMinutes)}`;
  preview.style.left = `${e.clientX + 12}px`;
  preview.style.top = `${e.clientY + 12}px`;
  preview.classList.remove("hidden");
});

document.addEventListener("mouseleave", hideHoverPreview);

// Re-apply assignment mode UI after HTMX swaps the grid (e.g. room pagination).
// Module state survives HTMX swaps but DOM classes do not.
document.body.addEventListener("htmx:afterSwap", () => {
  if (armed) {
    banner().classList.remove("hidden");
    markColumnsActive(true);
    renderPreferredSlotOverlays();
  }
});

// Keep #timetable-grid's auto-refresh URL aligned with the current browser URL,
// so an assign/unassign after pagination reloads the page the user is viewing
// (not the page that was originally rendered).
document.body.addEventListener("htmx:pushedIntoHistory", () => {
  const gridEl = grid();
  const hxGet = gridEl.getAttribute("hx-get") ?? "";
  const baseUrl = hxGet.split("?")[0];
  gridEl.setAttribute("hx-get", baseUrl + globalThis.location.search);
});

// Cancel button — delegated so it survives HTMX swaps of any ancestor
document.addEventListener("click", (e) => {
  const target = e.target as Element;
  if (target.closest("#assign-mode-cancel")) {
    exitAssignMode();
  }
});

// Escape key
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && armed) {
    exitAssignMode();
  }
});

// --- Column width -----------------------------------------------------------
// Every column is one CSS track of the same width, so a single stored number
// drives the whole calendar. It lives on the document element rather than on
// the calendar, which HTMX replaces wholesale on every pagination or refresh.
// The default is the CSS fallback in timetable.css, never restated here.

const COLUMN_WIDTH_KEY = "timetable.columnWidth";
const COLUMN_WIDTH_MIN = 80;
const COLUMN_WIDTH_MAX = 512;
const COLUMN_WIDTH_STEP = 16;
const GRIP_FALLBACK_PX = 14;
const COLUMN_WIDTH_KEY_STEPS: Record<string, number> = {
  ArrowLeft: -COLUMN_WIDTH_STEP,
  ArrowRight: COLUMN_WIDTH_STEP,
};

const resizer = (): HTMLElement | null =>
  document.querySelector<HTMLElement>(".timetable-column-resizer");

const roomCells = (): HTMLElement[] => [
  ...document.querySelectorAll<HTMLElement>(".timetable-room-cell"),
];

const clampColumnWidth = (px: number): number =>
  Math.round(Math.min(COLUMN_WIDTH_MAX, Math.max(COLUMN_WIDTH_MIN, px)));

// The rendered width, not the stored one: under the stored width the tracks
// stretch to fill the calendar (`minmax(w, 1fr)`), and that is what the handle
// has to report and step from. Reads layout, so never call it mid-drag.
const renderedColumnWidth = (): number =>
  roomCells()[0]?.getBoundingClientRect().width ?? COLUMN_WIDTH_MIN;

function storedColumnWidth(): number | null {
  const parsed = Number.parseFloat(localStorage.getItem(COLUMN_WIDTH_KEY) ?? "");
  return Number.isFinite(parsed) ? clampColumnWidth(parsed) : null;
}

// Paint only. Runs per pointermove, so it touches nothing but the property.
const applyColumnWidth = (width: number): void =>
  document.documentElement.style.setProperty("--timetable-column-width", `${width}px`);

// The bounds live here alone; the template ships a static separator and this is
// what promotes it to a focusable one, so a missing bundle leaves no dead tab
// stop behind.
function announceColumnWidth(): void {
  const handle = resizer();
  if (!handle) return;
  const now = Math.round(renderedColumnWidth());
  handle.tabIndex = 0;
  handle.setAttribute("aria-valuemin", String(COLUMN_WIDTH_MIN));
  handle.setAttribute("aria-valuemax", String(COLUMN_WIDTH_MAX));
  handle.setAttribute("aria-valuenow", String(now));
  handle.setAttribute("aria-valuetext", `${now} px`);
}

// Paint, persist and announce together -- for the discrete changes (keyboard,
// end of a drag), never for a drag frame.
function commitColumnWidth(width: number): void {
  applyColumnWidth(width);
  localStorage.setItem(COLUMN_WIDTH_KEY, String(width));
  announceColumnWidth();
}

function resetColumnWidth(): void {
  document.documentElement.style.removeProperty("--timetable-column-width");
  localStorage.removeItem(COLUMN_WIDTH_KEY);
  announceColumnWidth();
}

// Every room border is a grip (a ::after, so there are no nodes to hit): a
// pointerdown counts as a grab when it lands within one grip of the right edge.
function grabbedCell(e: PointerEvent): HTMLElement | null {
  const cell = (e.target as Element).closest?.<HTMLElement>(".timetable-room-cell");
  if (!cell) return null;
  // Measured off the one real handle, which the same custom property sizes, so
  // the grip width stays in CSS instead of being restated here in pixels.
  const grip = resizer()?.getBoundingClientRect().width || GRIP_FALLBACK_PX;
  return e.clientX >= cell.getBoundingClientRect().right - grip ? cell : null;
}

// The grabbed border closes `index + 1` equal columns counted from where the
// first one starts, so the travel divides by that many. Widening pushes every
// column left of the border along too, and folding that into the same step is
// what keeps the border under the cursor instead of running away from it.
function columnWidthFromPointer(index: number, left: number, clientX: number): number {
  return clampColumnWidth((clientX - left) / (index + 1));
}

document.addEventListener("pointerdown", (e) => {
  const cell = e.button === 0 ? grabbedCell(e) : null;
  if (!cell) return;
  e.preventDefault();

  const cells = roomCells();
  const index = cells.indexOf(cell);
  const [first] = cells;
  if (index === -1 || !first) return;

  // Measured once: the drag reads no layout after this, and the first column's
  // left edge cannot move -- the time column ahead of it is a fixed track.
  const { left } = first.getBoundingClientRect();
  // Resize from wherever inside the grip the drag started, so the border does
  // not jump to the cursor on the first move.
  const grabOffset = e.clientX - cell.getBoundingClientRect().right;

  const target = e.target as HTMLElement;
  target.setPointerCapture(e.pointerId);
  cell.classList.add("is-resizing");
  document.documentElement.classList.add("timetable-resizing");

  let width = renderedColumnWidth();
  const onMove = (move: PointerEvent): void => {
    width = columnWidthFromPointer(index, left, move.clientX - grabOffset);
    applyColumnWidth(width);
  };
  const onEnd = (): void => {
    target.removeEventListener("pointermove", onMove);
    target.removeEventListener("pointerup", onEnd);
    target.removeEventListener("pointercancel", onEnd);
    cell.classList.remove("is-resizing");
    document.documentElement.classList.remove("timetable-resizing");
    commitColumnWidth(width);
  };

  target.addEventListener("pointermove", onMove);
  target.addEventListener("pointerup", onEnd);
  target.addEventListener("pointercancel", onEnd);
});

document.addEventListener("dblclick", (e) => {
  if (grabbedCell(e as unknown as PointerEvent)) resetColumnWidth();
});

document.addEventListener("keydown", (e) => {
  if (!(e.target as Element).closest?.(".timetable-column-resizer")) return;

  if (e.key in COLUMN_WIDTH_KEY_STEPS) {
    e.preventDefault();
    commitColumnWidth(clampColumnWidth(renderedColumnWidth() + COLUMN_WIDTH_KEY_STEPS[e.key]));
  } else if (e.key === "Home") {
    e.preventDefault();
    commitColumnWidth(COLUMN_WIDTH_MIN);
  } else if (e.key === "End") {
    e.preventDefault();
    commitColumnWidth(COLUMN_WIDTH_MAX);
  }
});

// The width itself survives an HTMX swap on its own -- it is set above every
// node HTMX replaces -- but the handle inside the new markup is static until
// this promotes it again.
document.body.addEventListener("htmx:load", announceColumnWidth);

const storedWidth = storedColumnWidth();
if (storedWidth !== null) applyColumnWidth(storedWidth);
announceColumnWidth();
