// Optimistic roster in the session modal. The one-click enroll, waitlist and
// cancel forms swap only the footer, so on submit the participants tab and
// panel show the viewer's change at once. The server answers with a
// roster-sync event carrying the real outcome, which replaces the guess; a
// request that ends without one (network error, 5xx, redirect) restores what
// the panel showed before.

import { numberWaitingPositions } from "./waiting-positions";

type RosterStatus = "" | "confirmed" | "waiting";

interface RosterState {
  enrolled: number;
  limit: string;
  status: RosterStatus;
  waiting: number;
}

interface RosterSync {
  enrolled: number;
  limit: number;
  session: number;
  status: string;
  waiting: number;
}

interface RosterRequest {
  action: string;
  session: string;
}

const ACTION_STATUS: Record<string, RosterStatus> = {
  cancel: "",
  enroll: "confirmed",
  waitlist: "waiting",
};

// Where the viewer's own row sat, so a rollback puts that row back with its
// place in the list and its join time, rather than a fresh copy at the end.
interface Placement {
  list: Element;
  next: Node | null;
  row: Element;
}

// The panel as it stood before a request still in flight.
interface Pending {
  placement: Placement | null;
  state: RosterState;
}

const SELF_ROW = "[data-roster-list] > [data-roster-self]";

const pending = new Map<string, Pending>();

// htmx re-fires htmx:afterRequest on an ancestor once a swap has detached the
// form, and then names that ancestor as the event's element. The request
// object is the one thing both firings share.
const inFlight = new WeakMap<object, string>();

const panelFor = (session: string): HTMLElement | null =>
  document.querySelector<HTMLElement>(`[data-roster="${session}"]`);

const toStatus = (value: string | undefined): RosterStatus =>
  value === "confirmed" || value === "waiting" ? value : "";

const seated = (status: RosterStatus): number => (status === "confirmed" ? 1 : 0);

const queued = (status: RosterStatus): number => (status === "waiting" ? 1 : 0);

const selfStatus = (panel: HTMLElement): RosterStatus => {
  const self = panel.querySelector(SELF_ROW);
  return toStatus(self?.closest<HTMLElement>("[data-roster-group]")?.dataset.rosterGroup);
};

const readState = (panel: HTMLElement): RosterState => ({
  enrolled: Number(panel.dataset.rosterEnrolled),
  limit: panel.querySelector("[data-roster-limit]")?.textContent ?? "",
  status: selfStatus(panel),
  waiting: Number(panel.dataset.rosterWaiting),
});

const predict = (before: RosterState, action: string): RosterState => {
  const status = ACTION_STATUS[action] ?? before.status;
  return {
    enrolled: Math.max(0, before.enrolled - seated(before.status) + seated(status)),
    limit: before.limit,
    status,
    waiting: Math.max(0, before.waiting - queued(before.status) + queued(status)),
  };
};

const placementOf = (panel: HTMLElement): Placement | null => {
  const row = panel.querySelector(SELF_ROW);
  const list = row?.parentElement;
  return row && list ? { list, next: row.nextSibling, row } : null;
};

const addSelf = (panel: HTMLElement, status: RosterStatus): void => {
  const group = `[data-roster-group="${status}"]`;
  const template = panel.querySelector<HTMLTemplateElement>(
    `${group} template[data-roster-self-template]`,
  );
  const list = panel.querySelector(`${group} [data-roster-list]`);
  if (template && list) list.append(template.content.cloneNode(true));
};

// The saved row comes back only when the outcome is the status it had; any
// other outcome is a new row.
const showSelf = (panel: HTMLElement, status: RosterStatus, saved?: Pending): void => {
  for (const row of panel.querySelectorAll(SELF_ROW)) row.remove();
  const placement = saved?.state.status === status ? saved.placement : null;
  if (placement) placement.list.insertBefore(placement.row, placement.next);
  else addSelf(panel, status);
};

const setHidden = (root: ParentNode, selector: string, hidden: boolean): void => {
  const element = root.querySelector<HTMLElement>(selector);
  if (element) element.hidden = hidden;
};

const setText = (root: ParentNode, selector: string, text: string): void => {
  const element = root.querySelector(selector);
  if (element) element.textContent = text;
};

// Mirrors the hidden rules _session_participants_panel.html renders with.
const hiddenWhen = ({ enrolled, waiting }: RosterState): [string, boolean][] => [
  ['[data-roster-group="confirmed"]', enrolled === 0],
  ['[data-roster-group="waiting"]', waiting === 0],
  ['[data-roster-empty="waiting"]', waiting > 0 || enrolled === 0],
  ['[data-roster-empty="all"]', waiting > 0 || enrolled > 0],
];

const renderPanel = (panel: HTMLElement, state: RosterState, saved?: Pending): void => {
  showSelf(panel, state.status, saved);
  panel.dataset.rosterEnrolled = String(state.enrolled);
  panel.dataset.rosterWaiting = String(state.waiting);
  setText(panel, "[data-roster-count]", String(state.enrolled));
  setText(panel, "[data-roster-limit]", state.limit);
  for (const [selector, hidden] of hiddenWhen(state)) setHidden(panel, selector, hidden);
  numberWaitingPositions(document);
};

const renderTab = (panel: HTMLElement, state: RosterState): void => {
  const tab = document.querySelector(`[role="tab"][aria-controls="${panel.id}"]`);
  if (!tab) return;
  setText(tab, '[data-roster-badge="confirmed"]', String(state.enrolled));
  setText(tab, '[data-roster-badge="waiting"]', `+${state.waiting}`);
  setHidden(tab, '[data-roster-badge="waiting"]', state.waiting === 0);
};

const render = (panel: HTMLElement, state: RosterState, saved?: Pending): void => {
  renderPanel(panel, state, saved);
  renderTab(panel, state);
};

const eventForm = (e: Event): HTMLFormElement | null => {
  const elt = (e as CustomEvent<{ elt?: unknown }>).detail?.elt;
  return elt instanceof HTMLFormElement ? elt : null;
};

const rosterRequest = (e: Event): RosterRequest | null => {
  const { rosterAction = "", rosterSession = "" } = eventForm(e)?.dataset ?? {};
  return rosterSession ? { action: rosterAction, session: rosterSession } : null;
};

const requestPanel = (request: RosterRequest | null): HTMLElement | null =>
  request ? panelFor(request.session) : null;

const requestXhr = (e: Event): object | undefined =>
  (e as CustomEvent<{ xhr?: object }>).detail?.xhr;

const track = (e: Event, session: string): void => {
  const xhr = requestXhr(e);
  if (xhr) inFlight.set(xhr, session);
};

// A second submit before the first answers keeps the first snapshot: that is
// the last state the server confirmed.
const remember = (session: string, panel: HTMLElement): void => {
  if (pending.has(session)) return;
  pending.set(session, { placement: placementOf(panel), state: readState(panel) });
};

const restore = (session: string): void => {
  const saved = pending.get(session);
  const panel = panelFor(session);
  pending.delete(session);
  if (saved && panel) render(panel, saved.state, saved);
};

document.body.addEventListener("htmx:beforeRequest", (e) => {
  const request = rosterRequest(e);
  const panel = requestPanel(request);
  if (!request || !panel) return;
  track(e, request.session);
  remember(request.session, panel);
  render(panel, predict(readState(panel), request.action));
});

// Sent by the enroll view in its HX-Trigger header, so htmx fires it before
// the footer swap and before htmx:afterRequest.
document.body.addEventListener("roster-sync", (e) => {
  const sync = (e as CustomEvent<RosterSync>).detail;
  const session = String(sync.session);
  const saved = pending.get(session);
  pending.delete(session);
  const panel = panelFor(session);
  if (!panel) return;
  const state = {
    enrolled: sync.enrolled,
    limit: String(sync.limit),
    status: toStatus(sync.status),
    waiting: sync.waiting,
  };
  render(panel, state, saved);
});

// Still pending here means no roster-sync came back: put the panel back.
document.body.addEventListener("htmx:afterRequest", (e) => {
  const xhr = requestXhr(e);
  const session = xhr && inFlight.get(xhr);
  if (session) restore(session);
});
