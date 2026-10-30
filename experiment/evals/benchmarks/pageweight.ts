import { createRequire } from "node:module";

import type { StoredCookie } from "./auth.ts";

const require = createRequire(import.meta.url);

type PlaywrightModule = typeof import("playwright");

const loadPlaywright = (): PlaywrightModule => {
  try {
    return require("playwright");
  } catch {
    return require("/home/user/ludamus/tests/e2e/node_modules/@playwright/test");
  }
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

export const measurePageWeight = async (
  url: string,
  cookies: ReadonlyArray<StoredCookie>,
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
  await context.addInitScript(() => {
    window.localStorage.setItem("prologue.consent", "declined");
  });

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

  const timing = await page.evaluate(() => {
    const navigation = performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming;
    const vitals = (window as unknown as { __vitals: { lcp: number | null; cls: number } }).__vitals;

    return {
      cls: vitals.cls,
      domContentLoaded: navigation.domContentLoadedEventEnd,
      lcp: vitals.lcp,
      load: navigation.loadEventEnd,
    };
  });

  await browser.close();

  return {
    byType,
    consoleErrors,
    cssBytes: byType.stylesheet?.bytes ?? 0,
    cumulativeLayoutShift: timing.cls,
    domContentLoadedMs: Math.round(timing.domContentLoaded),
    htmlBytes: byType.document?.bytes ?? 0,
    jsBytes: byType.script?.bytes ?? 0,
    largestContentfulPaintMs: timing.lcp === null ? null : Math.round(timing.lcp),
    loadMs: Math.round(timing.load),
    requests,
    status: response?.status() ?? 0,
    transferBytes,
    url,
  };
};
