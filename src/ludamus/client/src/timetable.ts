interface PreferredSlot {
  end: string;
  start: string;
}

let assignSessionPk: string | null = null;
let assignDuration = 0;
let assignBackUrl: string | null = null;
let assignPreferredSlots: PreferredSlot[] = [];

declare const htmx: {
  ajax: (
    method: string,
    url: string,
    opts: { swap: string; target: string },
  ) => void;
};

const banner = (): HTMLElement =>
  document.getElementById("assign-mode-banner")!;

const grid = (): HTMLElement => document.getElementById("timetable-grid")!;

const calendar = (): HTMLElement | null =>
  document.getElementById("timetable-calendar");

const columns = (): NodeListOf<HTMLElement> =>
  document.querySelectorAll<HTMLElement>(".timetable-column");

const csrfToken = (): string =>
  (document.querySelector("[name=csrfmiddlewaretoken]") as HTMLInputElement)
    .value;

function pxPerMinute(cal: HTMLElement): number {
  const raw = getComputedStyle(cal).getPropertyValue("--minute-px").trim();
  const parsed = Number.parseFloat(raw);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1;
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
  for (const el of document.querySelectorAll<HTMLElement>(
    ".timetable-preferred-slot",
  ))
    el.remove();
}

function renderPreferredSlotOverlays(): void {
  clearPreferredSlotOverlays();
  if (assignPreferredSlots.length === 0) return;
  const cal = calendar();
  if (!cal) return;
  const { eventStart } = cal.dataset;
  if (!eventStart) return;

  const totalMinutes = Number(cal.dataset.totalMinutes);
  if (!totalMinutes) return;

  const eventStartMs = new Date(eventStart).getTime();
  const minutePx = pxPerMinute(cal);
  const pxPerMs = minutePx / 60_000;
  const totalHeightPx = totalMinutes * minutePx;
  const cols = columns();
  if (cols.length === 0) return;

  for (const slot of assignPreferredSlots) {
    const startMs = new Date(slot.start).getTime();
    const endMs = new Date(slot.end).getTime();
    if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) continue;

    const rawTop = (startMs - eventStartMs) * pxPerMs;
    const rawBottom = (endMs - eventStartMs) * pxPerMs;
    const top = Math.max(0, rawTop);
    const bottom = Math.min(totalHeightPx, rawBottom);
    if (bottom <= top) continue;

    for (const col of cols) {
      const overlay = document.createElement("div");
      overlay.className = "timetable-preferred-slot";
      overlay.style.top = `calc(${top}px + 20px)`;
      overlay.style.height = `${bottom - top}px`;
      col.append(overlay);
    }
  }
}

function enterAssignMode(
  sessionPk: string,
  duration: number,
  backUrl: string | null,
  preferredSlots: PreferredSlot[],
): void {
  assignSessionPk = sessionPk;
  assignDuration = duration;
  assignBackUrl = backUrl;
  assignPreferredSlots = preferredSlots;

  banner().classList.remove("hidden");
  for (const col of columns()) col.classList.add("assign-mode-active");
  renderPreferredSlotOverlays();
}

function exitAssignMode(): void {
  assignSessionPk = null;
  assignDuration = 0;
  assignBackUrl = null;
  assignPreferredSlots = [];

  banner().classList.add("hidden");
  for (const col of columns()) col.classList.remove("assign-mode-active");
  clearPreferredSlotOverlays();
}

// Delegate click on Assign buttons inside the left pane
document.addEventListener("click", (e) => {
  const target = e.target as Element;

  const assignBtn = target.closest<HTMLElement>("[data-assign-session-pk]");
  if (assignBtn) {
    const pk = assignBtn.dataset.assignSessionPk!;
    const duration = Number(assignBtn.dataset.assignDuration) || 60;
    const backUrl = assignBtn.dataset.assignBackUrl ?? null;
    const slots = parsePreferredSlots(assignBtn.dataset.assignPreferredSlots);
    enterAssignMode(pk, duration, backUrl, slots);
    return;
  }

  // Grid column click during assignment mode
  if (assignSessionPk) {
    const col = target.closest<HTMLElement>(
      ".timetable-column.assign-mode-active",
    );
    if (col) {
      const spacePk = col.dataset.spacePk!;
      const cal = calendar()!;
      const eventStart = cal.dataset.eventStart!;
      const slotMinutes = Number(cal.dataset.slotMinutes);
      const pxPerSlot = slotMinutes * pxPerMinute(cal);

      const rect = col.getBoundingClientRect();
      const yOffset = e instanceof MouseEvent ? e.clientY - rect.top : 0;
      const slotIndex = Math.floor(yOffset / pxPerSlot);
      const offsetMinutes = slotIndex * slotMinutes;

      const startDt = new Date(eventStart);
      startDt.setMinutes(startDt.getMinutes() + offsetMinutes);
      const endDt = new Date(startDt.getTime() + assignDuration * 60_000);

      const assignUrl = grid().dataset.assignUrl!;
      const body = new FormData();
      body.append("session_pk", assignSessionPk);
      body.append("space_pk", spacePk);
      body.append("start_time", startDt.toISOString());
      body.append("end_time", endDt.toISOString());
      body.append("csrfmiddlewaretoken", csrfToken());

      const sessionPkAtClick = assignSessionPk;
      const durationAtClick = assignDuration;
      const backUrlAtClick = assignBackUrl;
      const slotsAtClick = assignPreferredSlots;
      exitAssignMode();

      fetch(assignUrl, { body, method: "POST" })
        .then((resp) => {
          if (resp.ok) {
            document.body.dispatchEvent(new CustomEvent("timetableChanged"));
            if (backUrlAtClick) {
              htmx.ajax("GET", backUrlAtClick, {
                swap: "outerHTML",
                target: "#left-pane",
              });
            }
          } else {
            alert(
              `Could not place session (server returned ${resp.status}). ` +
                `Please try again.`,
            );
            enterAssignMode(
              sessionPkAtClick,
              durationAtClick,
              backUrlAtClick,
              slotsAtClick,
            );
          }
        })
        .catch(() => {
          alert("Network error placing session. Please try again.");
          enterAssignMode(
            sessionPkAtClick,
            durationAtClick,
            backUrlAtClick,
            slotsAtClick,
          );
        });
      return;
    }
  }
});

// Re-apply assignment mode UI after HTMX swaps the grid (e.g. room pagination).
// Module state survives HTMX swaps but DOM classes do not.
document.body.addEventListener("htmx:afterSwap", () => {
  if (assignSessionPk) {
    banner().classList.remove("hidden");
    for (const col of columns()) col.classList.add("assign-mode-active");
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
  if (e.key === "Escape" && assignSessionPk) {
    exitAssignMode();
  }
});
