import { createRequire } from "node:module";
import path from "node:path";

import { Predicate, Schema } from "effect";

import type { StoredCookie } from "./auth.ts";

type SerializedValue =
  | string
  | number
  | boolean
  | null
  | readonly SerializedValue[]
  | { readonly [key: string]: SerializedValue };

interface RequestSizes {
  readonly responseBodySize: number;
  readonly responseHeadersSize: number;
}

interface BrowserRequest {
  readonly resourceType: () => string;
  readonly sizes: () => Promise<RequestSizes>;
}

interface BrowserResponse {
  readonly request: () => BrowserRequest;
  readonly status: () => number;
}

interface ConsoleMessage {
  readonly type: () => string;
}

interface BrowserPage {
  readonly evaluate: (expression: string) => Promise<SerializedValue>;
  readonly goto: (
    url: string,
    options: { readonly waitUntil: "load" }
  ) => Promise<BrowserResponse | null>;
  readonly on: {
    (event: "console", listener: (message: ConsoleMessage) => void): void;
    (
      event: "response",
      listener: (response: BrowserResponse) => Promise<void>
    ): void;
  };
  readonly waitForTimeout: (milliseconds: number) => Promise<void>;
}

interface SessionCookie {
  readonly domain: string;
  readonly name: string;
  readonly path: string;
  readonly value: string;
}

interface BrowserContext {
  readonly addCookies: (cookies: readonly SessionCookie[]) => Promise<void>;
  readonly addInitScript: (script: string) => Promise<void>;
  readonly newPage: () => Promise<BrowserPage>;
}

interface Browser {
  readonly close: () => Promise<void>;
  readonly newContext: (options: {
    readonly locale: string;
  }) => Promise<BrowserContext>;
}

interface PlaywrightLibrary {
  readonly chromium: { readonly launch: () => Promise<Browser> };
}

const require = createRequire(import.meta.url);

const e2ePlaywright = path.resolve(
  import.meta.dirname,
  "../../../tests/e2e/node_modules/@playwright/test"
);

const isPlaywrightLibrary = (loaded: unknown): loaded is PlaywrightLibrary =>
  Predicate.hasProperty(loaded, "chromium") &&
  Predicate.hasProperty(loaded.chromium, "launch") &&
  Predicate.isFunction(loaded.chromium.launch);

const loadPlaywright = (): PlaywrightLibrary => {
  let loaded: unknown;

  try {
    loaded = require("playwright");
  } catch {
    loaded = require(e2ePlaywright);
  }

  if (!isPlaywrightLibrary(loaded)) {
    throw new Error("playwright loaded without chromium.launch");
  }

  return loaded;
};

export type ResourceBytes = Record<string, { count: number; bytes: number }>;

export type PageWeight = Readonly<{
  url: string;
  status: number;
  requests: number;
  transferBytes: number;
  byType: ResourceBytes;
  domContentLoadedMs: number;
  loadMs: number;
  largestContentfulPaintMs: number | null;
  cumulativeLayoutShift: number | null;
  consoleErrors: number;
  htmlBytes: number;
  jsBytes: number;
  cssBytes: number;
}>;

const vitalsScript = `
  window.__vitals = { lcp: null, cls: 0 };
  new PerformanceObserver((list) => {
    for (const entry of list.getEntries()) window.__vitals.lcp = entry.startTime;
  }).observe({ type: "largest-contentful-paint", buffered: true });
  new PerformanceObserver((list) => {
    for (const entry of list.getEntries()) if (!entry.hadRecentInput) window.__vitals.cls += entry.value;
  }).observe({ type: "layout-shift", buffered: true });
`;

const declineConsentScript = `window.localStorage.setItem("prologue.consent", "declined");`;

const timingScript = `(() => {
  const navigation = performance.getEntriesByType("navigation")[0];
  const vitals = window.__vitals;
  return {
    cls: vitals.cls,
    domContentLoaded: navigation.domContentLoadedEventEnd,
    lcp: vitals.lcp,
    load: navigation.loadEventEnd,
  };
})()`;

const BrowserTiming = Schema.Struct({
  cls: Schema.Number,
  domContentLoaded: Schema.Number,
  lcp: Schema.NullOr(Schema.Number),
  load: Schema.Number,
});

export const measurePageWeight = async (
  url: string,
  cookies: readonly StoredCookie[],
  origin: string
): Promise<PageWeight> => {
  const { chromium } = loadPlaywright();
  const browser = await chromium.launch();
  const context = await browser.newContext({ locale: "en-US" });
  const host = new URL(origin).hostname;

  if (cookies.length > 0) {
    await context.addCookies(
      cookies.map((cookie) => ({
        domain: host,
        name: cookie.name,
        path: "/",
        value: cookie.value,
      }))
    );
  }

  await context.addInitScript(vitalsScript);
  await context.addInitScript(declineConsentScript);

  const page = await context.newPage();
  const byType: ResourceBytes = {};
  let requests = 0;
  let transferBytes = 0;
  let consoleErrors = 0;

  page.on("console", (message) => {
    if (message.type() === "error") {
      consoleErrors += 1;
    }
  });
  page.on("response", async (response) => {
    requests += 1;
    const type = response.request().resourceType();
    let size = 0;

    try {
      const sizes = await response.request().sizes();
      size = sizes.responseBodySize + sizes.responseHeadersSize;
    } catch {
      size = 0;
    }

    transferBytes += size;
    const bucket = byType[type] ?? { bytes: 0, count: 0 };
    byType[type] = { bytes: bucket.bytes + size, count: bucket.count + 1 };
  });

  const response = await page.goto(url, { waitUntil: "load" });
  await page.waitForTimeout(1500);

  const timing = Schema.decodeUnknownSync(BrowserTiming)(
    await page.evaluate(timingScript)
  );

  await browser.close();

  return {
    byType,
    consoleErrors,
    cssBytes: byType.stylesheet?.bytes ?? 0,
    cumulativeLayoutShift: timing.cls,
    domContentLoadedMs: Math.round(timing.domContentLoaded),
    htmlBytes: byType.document?.bytes ?? 0,
    jsBytes: byType.script?.bytes ?? 0,
    largestContentfulPaintMs:
      timing.lcp === null ? null : Math.round(timing.lcp),
    loadMs: Math.round(timing.load),
    requests,
    status: response?.status() ?? 0,
    transferBytes,
    url,
  };
};
