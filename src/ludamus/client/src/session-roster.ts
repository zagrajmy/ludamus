// Optimistic roster in the session modal. The one-click enroll, waitlist and
// cancel forms swap only the footer, so on submit the avatar stack, seat
// counts, and the participants popover show the viewer's change at once. The
// server answers with a roster-sync event carrying the real outcome, which
// replaces the guess; a request that ends without one (network error, 5xx,
// redirect) restores what the stack and lists showed before.

import "./session-roster.css";

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

const STACK_CAP = 4;

// Where the viewer's own face or row sat, so a rollback puts that node back
// with its place rather than a fresh copy at the end.
interface Placement {
  list: Element;
  next: Node | null;
  row: Element;
}

interface Pending {
  panel: Placement | null;
  stack: Placement | null;
  state: RosterState;
}

const STACK_SELF = "[data-roster-stack] > [data-roster-self]";
const PANEL_SELF = "[data-roster-list] > [data-roster-self]";

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

const selfStatus = (root: HTMLElement): RosterStatus => toStatus(root.dataset.rosterStatus);

const readState = (root: HTMLElement): RosterState => ({
  enrolled: Number(root.dataset.rosterEnrolled),
  limit: root.querySelector("[data-roster-limit]")?.textContent ?? "",
  status: selfStatus(root),
  waiting: Number(root.dataset.rosterWaiting),
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

const placementOf = (root: HTMLElement, selector: string): Placement | null => {
  const row = root.querySelector(selector);
  const list = row?.parentElement;
  return row && list ? { list, next: row.nextSibling, row } : null;
};

const addFromTemplate = (root: HTMLElement, kind: string, listSelector: string): void => {
  const template = root.querySelector<HTMLTemplateElement>(
    `template[data-roster-self-template][data-roster-kind="${kind}"]`,
  );
  const list = root.querySelector(listSelector);
  if (template && list) list.append(template.content.cloneNode(true));
};

interface PutSelf {
  kind: string;
  listSelector: string;
  placement: Placement | null;
  room: () => boolean;
  selector: string;
  show: boolean;
}

const clearMatching = (root: HTMLElement, selector: string): void => {
  for (const row of root.querySelectorAll(selector)) row.remove();
};

// Drop every copy of the viewer's own node, then put one back when `show` —
// either the saved placement (rollback / same-status sync) or a fresh clone,
// unless `room` says the list is already full (the stack's four-face cap).
const putSelf = (root: HTMLElement, spec: PutSelf): void => {
  clearMatching(root, spec.selector);
  if (!spec.show) return;
  if (spec.placement) {
    spec.placement.list.insertBefore(spec.placement.row, spec.placement.next);
    return;
  }
  if (spec.room()) addFromTemplate(root, spec.kind, spec.listSelector);
};

const showStackSelf = (root: HTMLElement, status: RosterStatus, saved?: Pending): void => {
  putSelf(root, {
    kind: "stack",
    listSelector: "[data-roster-stack]",
    placement: saved?.state.status === "confirmed" ? saved.stack : null,
    room: () => {
      const stack = root.querySelector("[data-roster-stack]");
      return Boolean(stack && stack.childElementCount < STACK_CAP);
    },
    selector: STACK_SELF,
    show: status === "confirmed",
  });
};

const showPanelSelf = (root: HTMLElement, status: RosterStatus, saved?: Pending): void => {
  putSelf(root, {
    kind: status,
    listSelector: `[data-roster-group="${status}"] [data-roster-list]`,
    placement: saved?.state.status === status ? saved.panel : null,
    room: () => true,
    selector: PANEL_SELF,
    show: Boolean(status),
  });
};

const setHidden = (root: ParentNode, selector: string, hidden: boolean): void => {
  const element = root.querySelector<HTMLElement>(selector);
  if (element) element.hidden = hidden;
};

const setText = (root: ParentNode, selector: string, text: string): void => {
  for (const element of root.querySelectorAll(selector)) {
    element.textContent = text;
  }
};

// Mirrors the hidden rules _session_roster.html renders with.
const hiddenWhen = ({ enrolled, waiting }: RosterState): [string, boolean][] => [
  ["[data-roster-stack]", enrolled === 0],
  ["[data-roster-empty-icon]", enrolled > 0],
  ["[data-roster-waiting-block]", waiting === 0],
  ['[data-roster-group="confirmed"]', enrolled === 0],
  ['[data-roster-group="waiting"]', waiting === 0],
  ['[data-roster-empty="waiting"]', waiting > 0 || enrolled === 0],
  ['[data-roster-empty="all"]', waiting > 0 || enrolled > 0],
];

const render = (root: HTMLElement, state: RosterState, saved?: Pending): void => {
  showStackSelf(root, state.status, saved);
  showPanelSelf(root, state.status, saved);
  root.dataset.rosterEnrolled = String(state.enrolled);
  root.dataset.rosterWaiting = String(state.waiting);
  root.dataset.rosterStatus = state.status;
  setText(root, "[data-roster-count]", String(state.enrolled));
  setText(root, "[data-roster-limit]", state.limit);
  setText(root, "[data-roster-waiting-count]", String(state.waiting));
  for (const [selector, hidden] of hiddenWhen(state)) setHidden(root, selector, hidden);
  numberWaitingPositions(root);
};

const eventForm = (e: Event): HTMLFormElement | null => {
  const elt = (e as CustomEvent<{ elt?: unknown }>).detail?.elt;
  return elt instanceof HTMLFormElement ? elt : null;
};

const rosterRequest = (e: Event): RosterRequest | null => {
  const { rosterAction = "", rosterSession = "" } = eventForm(e)?.dataset ?? {};
  return rosterSession ? { action: rosterAction, session: rosterSession } : null;
};

const requestRoot = (request: RosterRequest | null): HTMLElement | null =>
  request ? panelFor(request.session) : null;

const requestXhr = (e: Event): object | undefined =>
  (e as CustomEvent<{ xhr?: object }>).detail?.xhr;

const track = (e: Event, session: string): void => {
  const xhr = requestXhr(e);
  if (xhr) inFlight.set(xhr, session);
};

// A second submit before the first answers keeps the first snapshot: that is
// the last state the server confirmed.
const remember = (session: string, root: HTMLElement): void => {
  if (pending.has(session)) return;
  pending.set(session, {
    panel: placementOf(root, PANEL_SELF),
    stack: placementOf(root, STACK_SELF),
    state: readState(root),
  });
};

const restore = (session: string): void => {
  const saved = pending.get(session);
  const root = panelFor(session);
  pending.delete(session);
  if (saved && root) render(root, saved.state, saved);
};

document.body.addEventListener("htmx:beforeRequest", (e) => {
  const request = rosterRequest(e);
  const root = requestRoot(request);
  if (!request || !root) return;
  track(e, request.session);
  remember(request.session, root);
  render(root, predict(readState(root), request.action));
});

// Sent by the enroll view in its HX-Trigger header, so htmx fires it before
// the footer swap and before htmx:afterRequest.
document.body.addEventListener("roster-sync", (e) => {
  const sync = (e as CustomEvent<RosterSync>).detail;
  const session = String(sync.session);
  const saved = pending.get(session);
  pending.delete(session);
  const root = panelFor(session);
  if (!root) return;
  const state = {
    enrolled: sync.enrolled,
    limit: String(sync.limit),
    status: toStatus(sync.status),
    waiting: sync.waiting,
  };
  render(root, state, saved);
});

// Still pending here means no roster-sync came back: put the stack back.
document.body.addEventListener("htmx:afterRequest", (e) => {
  const xhr = requestXhr(e);
  const session = xhr && inFlight.get(xhr);
  if (session) restore(session);
});

numberWaitingPositions(document);
