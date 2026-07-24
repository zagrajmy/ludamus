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
