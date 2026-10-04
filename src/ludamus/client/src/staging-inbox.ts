// Live updates for the captured-email inbox (/dev/emails/). Whoever opens it is
// waiting for mail they just triggered in another tab, so while the tab is
// visible it re-fetches itself and folds in whatever arrived.
//
// With no `m` in the URL the reader follows the newest email, so the whole
// inbox is swapped and the new mail opens. Once someone has picked an email,
// only the list changes; the message they're reading stays put. New rows flash
// once and are announced to screen readers.

const POLL_MS = 3000;
const FRESH_MS = 2500;

const announce = (count: number): void => {
  const region = document.querySelector<HTMLElement>("[data-inbox-announce]");
  if (!region) return;
  if (count === 0) return;
  region.textContent = (count === 1 ? region.dataset.one : region.dataset.many) ?? "";
};

const itemIds = (root: ParentNode): Set<string> =>
  new Set(
    Array.from(
      root.querySelectorAll<HTMLElement>("[data-inbox-item]"),
      (item) => item.dataset.inboxItem ?? "",
    ),
  );

const markFresh = (root: ParentNode, before: Set<string>): number => {
  const fresh = Array.from(
    root.querySelectorAll<HTMLElement>("[data-inbox-item]"),
    (item) => item,
  ).filter((item) => !before.has(item.dataset.inboxItem ?? ""));
  for (const item of fresh) item.dataset.fresh = "";
  globalThis.setTimeout(() => {
    for (const item of fresh) delete item.dataset.fresh;
  }, FRESH_MS);
  return fresh.length;
};

const swap = (current: HTMLElement, next: HTMLElement, followsNewest: boolean): void => {
  const before = itemIds(current);
  const focusedId =
    document.activeElement?.closest<HTMLElement>("[data-inbox-item]")?.dataset.inboxItem;

  let root = current;
  if (followsNewest) {
    current.replaceWith(next);
    root = next;
  } else {
    const list = current.querySelector("[data-inbox-list]");
    const nextList = next.querySelector("[data-inbox-list]");
    if (!list || !nextList) return;
    list.replaceWith(nextList);
    current.dataset.inboxNewest = next.dataset.inboxNewest;
  }

  if (focusedId) {
    root.querySelector<HTMLElement>(`[data-inbox-item="${CSS.escape(focusedId)}"]`)?.focus();
  }
  announce(markFresh(root, before));
};

let inFlight = false;

const check = async (): Promise<void> => {
  const current = document.querySelector<HTMLElement>("[data-inbox]");
  if (!current || document.hidden || inFlight) return;
  inFlight = true;
  try {
    const response = await fetch(globalThis.location.href, {
      cache: "no-store",
      credentials: "same-origin",
    });
    if (!response.ok) return;
    const page = new DOMParser().parseFromString(await response.text(), "text/html");
    const next = page.querySelector<HTMLElement>("[data-inbox]");
    if (!next || next.dataset.inboxNewest === current.dataset.inboxNewest) return;

    // The first email changes the whole page (search appears, the empty state
    // goes); a reload is the honest way to get there.
    if (!current.dataset.inboxNewest) {
      globalThis.location.reload();
      return;
    }

    const count = page.querySelector("[data-inbox-count]")?.textContent;
    const counter = document.querySelector("[data-inbox-count]");
    if (counter && count) counter.textContent = count;

    const followsNewest = !new URL(globalThis.location.href).searchParams.has("m");
    swap(current, next, followsNewest);
  } catch (error) {
    // A dropped poll (server restarting, laptop asleep) is retried on the next
    // tick; leave a trace instead of interrupting the reader.
    console.warn("Inbox refresh failed:", error);
  } finally {
    inFlight = false;
  }
};

if (document.querySelector("[data-inbox]")) {
  const live = document.querySelector<HTMLElement>("[data-inbox-live]");
  if (live) live.hidden = false;
  globalThis.setInterval(() => void check(), POLL_MS);
  document.addEventListener("visibilitychange", () => void check());
}
