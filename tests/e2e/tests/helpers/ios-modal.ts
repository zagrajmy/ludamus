import { type Browser, type BrowserContext, devices } from "@playwright/test";

const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:8000";

const installNavigationApi = (): void => {
  const listeners = new Set<(event: unknown) => void>();
  Object.defineProperty(window, "navigation", {
    configurable: true,
    value: {
      addEventListener: (type: string, cb: (event: unknown) => void) => {
        if (type === "navigate") listeners.add(cb);
      },
      removeEventListener: (type: string, cb: (event: unknown) => void) => {
        if (type === "navigate") listeners.delete(cb);
      },
    },
  });

  document.addEventListener("click", (event) => {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const anchor = event.target instanceof Element ? event.target.closest("a[href]") : null;
    if (
      !(anchor instanceof HTMLAnchorElement) ||
      anchor.target === "_blank" ||
      anchor.hasAttribute("download")
    )
      return;
    const url = new URL(anchor.href, location.href);
    if (url.origin !== location.origin) return;

    let intercepted = false;
    let handler: (() => Promise<void> | void) | undefined;
    const navigateEvent = {
      canIntercept: true,
      destination: { url: url.href },
      hashChange:
        url.pathname === location.pathname &&
        url.search === location.search &&
        url.hash !== location.hash,
      intercept: (options?: { handler?: () => Promise<void> | void }) => {
        intercepted = true;
        handler = options?.handler;
      },
      navigationType: "push",
    };
    for (const listener of listeners) listener(navigateEvent);
    if (!intercepted) return;

    event.preventDefault();
    history.pushState({}, "", url.href);
    if (handler) void Promise.resolve(handler());
  });
};

export const createIosModalContext = async (
  browser: Browser,
  browserName: string,
): Promise<BrowserContext> => {
  const context = await browser.newContext({
    ...devices["iPhone 14 Pro"],
    baseURL: BASE_URL,
  });
  if (browserName === "webkit") {
    await context.addInitScript(installNavigationApi);
  }
  return context;
};
