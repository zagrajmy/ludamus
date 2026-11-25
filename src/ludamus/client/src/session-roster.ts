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

// The panel as it stood before a request still in flight, by session.
const pending = new Map<string, RosterState>();

const panelFor = (session: string): HTMLElement | null =>
  document.querySelector<HTMLElement>(`[data-roster="${session}"]`);

const toStatus = (value: string | undefined): RosterStatus =>
  value === "confirmed" || value === "waiting" ? value : "";

const seated = (status: RosterStatus): number => (status === "confirmed" ? 1 : 0);

const queued = (status: RosterStatus): number => (status === "waiting" ? 1 : 0);

const selfStatus = (panel: HTMLElement): RosterStatus => {
  const self = panel.querySelector("[data-roster-list] > [data-roster-self]");
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

const showSelf = (panel: HTMLElement, status: RosterStatus): void => {
  for (const row of panel.querySelectorAll("[data-roster-list] > [data-roster-self]")) row.remove();
  const group = `[data-roster-group="${status}"]`;
  const template = panel.querySelector<HTMLTemplateElement>(
    `${group} template[data-roster-self-template]`,
  );
  const list = panel.querySelector(`${group} [data-roster-list]`);
  if (template && list) list.append(template.content.cloneNode(true));
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

const renderPanel = (panel: HTMLElement, state: RosterState): void => {
  showSelf(panel, state.status);
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

const render = (panel: HTMLElement, state: RosterState): void => {
  renderPanel(panel, state);
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

const restore = (session: string): void => {
  const before = pending.get(session);
  const panel = panelFor(session);
  pending.delete(session);
  if (before && panel) render(panel, before);
};

document.body.addEventListener("htmx:beforeRequest", (e) => {
  const request = rosterRequest(e);
  const panel = requestPanel(request);
  if (!request || !panel) return;
  const before = readState(panel);
  // A second submit before the first answers keeps the first snapshot: that
  // is the last state the server confirmed.
  pending.set(request.session, pending.get(request.session) ?? before);
  render(panel, predict(before, request.action));
});

// Sent by the enroll view in its HX-Trigger header, so htmx fires it before
// the footer swap and before htmx:afterRequest.
document.body.addEventListener("roster-sync", (e) => {
  const sync = (e as CustomEvent<RosterSync>).detail;
  const session = String(sync.session);
  pending.delete(session);
  const panel = panelFor(session);
  if (!panel) return;
  render(panel, {
    enrolled: sync.enrolled,
    limit: String(sync.limit),
    status: toStatus(sync.status),
    waiting: sync.waiting,
  });
});

// Still pending here means no roster-sync came back: put the panel back.
// The swap has detached the form, but its dataset still names the session,
// and htmx re-fires this event on the nearest attached ancestor so it
// reaches body once.
document.body.addEventListener("htmx:afterRequest", (e) => {
  const request = rosterRequest(e);
  if (request) restore(request.session);
});
