import type { Page } from "@playwright/test";

import path from "node:path";
import { gunzipSync } from "node:zlib";

import { attachArtifacts } from "./helpers/artifacts";
import { expect, test } from "./helpers/fixtures";

const PRIVACY_URL = "/crowd/profile/privacy/";
const AGE_URL = `${PRIVACY_URL}age/`;
const SPHERE_URL = "http://another.ludamus.localhost:8001/";
const state = (name: string) => path.join(__dirname, "..", `.auth-state-privacy-${name}.json`);
const isSdk = (url: string) => /module\.full\.no-external[^/]*\.js(?:\?|$)/u.test(url);

type Ingestion = { endpoint: string; events: string[] };

const recordingStarted = (page: Page, sdkUrl: string) =>
  page.evaluate(async (url) => {
    const { default: client } = (await import(url)) as {
      default: { sessionRecordingStarted(): boolean };
    };
    return client.sessionRecordingStarted();
  }, sdkUrl);

const captureBlocked = (page: Page, sdkUrl: string) =>
  page.evaluate(async (url) => {
    const { default: client } = (await import(url)) as {
      default: {
        capture(name: string, properties: object, options: object): unknown;
      };
    };
    return client.capture("privacy_revocation_probe", {}, { send_instantly: true }) === undefined;
  }, sdkUrl);

const changeAge = async (page: Page, age: "13–15" | "16 or older") => {
  await page.goto(AGE_URL);
  await page.getByRole("radio", { name: age, exact: true }).check();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByText(`Your age range is ${age}.`, { exact: false })).toBeVisible();
};

test.describe("Privacy revision across sphere origins", () => {
  test.use({
    baseURL: "http://ludamus.localhost:8001",
    storageState: state("revocation"),
    consentSeed: null,
  });

  test("revokes a loaded sibling tab and preserves newer consent in an older document", async ({
    page,
    context,
  }, testInfo) => {
    const ingestion: Ingestion[] = [];
    const sdkRequests: string[] = [];
    await page.addInitScript(() => {
      Reflect.deleteProperty(window, "cookieStore");
      // NOTE: PostHog drops bot captures before before_send, making a revocation assertion vacuous.
      Object.defineProperty(navigator, "webdriver", { get: () => false });
      Object.defineProperty(navigator, "userAgentData", { value: undefined });
    });
    await context.route("https://*.posthog.com/**", async (route) => {
      const url = new URL(route.request().url());
      if (/\/(?:e|s)\//u.test(url.pathname)) {
        const body = route.request().postDataBuffer();
        if (!body) throw new Error("Expected a PostHog ingestion body");
        const decoded = body[0] === 0x1f ? gunzipSync(body) : body;
        const payload = JSON.parse(decoded.toString("utf8")) as
          | { batch: { event: string }[] }
          | { event: string }
          | { event: string }[];
        const events = Array.isArray(payload)
          ? payload
          : "batch" in payload
            ? payload.batch
            : [payload];
        ingestion.push({ endpoint: url.pathname, events: events.map((event) => event.event) });
      }
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          featureFlags: {},
          sessionRecording: { endpoint: "/s/", sampleRate: 1 },
        }),
      });
    });
    page.on("request", (request) => {
      if (isSdk(request.url())) sdkRequests.push(request.url());
    });
    const root = await context.newPage();
    await changeAge(root, "16 or older");
    await page.goto(SPHERE_URL);
    expect(sdkRequests).toEqual([]);
    expect(await page.evaluate(() => typeof window.cookieStore)).toBe("undefined");
    const originalRevision = await context
      .cookies()
      .then((cookies) => cookies.find((cookie) => cookie.name === "ludamus.privacy")?.value);
    expect(originalRevision).toBeTruthy();
    expect(originalRevision).not.toBe("off");
    await page
      .getByRole("region", { name: "Cookie consent" })
      .getByRole("button", { name: "Cool" })
      .click();
    await expect.poll(() => sdkRequests.length).toBe(1);
    const [sdkUrl] = sdkRequests;
    await expect.poll(() => recordingStarted(page, sdkUrl)).toBe(true);
    const priorConsent = await page.evaluate(() => localStorage.getItem("prologue.consent"));
    expect(priorConsent).not.toBeNull();
    expect(await captureBlocked(page, sdkUrl)).toBe(false);
    await expect
      .poll(() => ingestion.flatMap((request) => request.events))
      .toContain("privacy_revocation_probe");
    await expect
      .poll(() => ingestion.some((request) => request.endpoint === "/s/"), { timeout: 15_000 })
      .toBe(true);

    const stale = await context.newPage();
    await stale.addInitScript(() => Reflect.deleteProperty(window, "cookieStore"));
    let release = () => {};
    const released = new Promise<void>((resolve) => {
      release = resolve;
    });
    const prologue = /\/prologue-[^/]+\.js(?:\?|$)/u;
    await stale.route(
      prologue,
      async (route) => {
        await released;
        await route.continue();
      },
      { times: 1 },
    );
    const delayedScript = stale.waitForRequest(prologue);
    await stale.goto(SPHERE_URL, { waitUntil: "commit" });
    await delayedScript;
    try {
      await changeAge(root, "13–15");
      expect(await captureBlocked(page, sdkUrl)).toBe(true);
      await expect.poll(() => recordingStarted(page, sdkUrl)).toBe(false);
      await expect
        .poll(() => page.evaluate(() => localStorage.getItem("prologue.consent")))
        .toBeNull();
      const stoppedAt = ingestion.length;
      await page.bringToFront();
      await page.getByRole("button", { name: "Account menu" }).click();
      expect(await captureBlocked(page, sdkUrl)).toBe(true);
      await expect.poll(() => recordingStarted(page, sdkUrl)).toBe(false);
      expect(ingestion).toHaveLength(stoppedAt);
      await expect(page.getByRole("region", { name: "Cookie consent" })).toBeHidden();

      await changeAge(root, "16 or older");
      const revision = await context
        .cookies()
        .then((cookies) => cookies.find((cookie) => cookie.name === "ludamus.privacy")?.value);
      expect(revision).not.toBe(originalRevision);
      expect(revision).not.toBe("off");
      expect(revision).toBeTruthy();
      await page.evaluate((stored) => {
        if (stored) localStorage.setItem("prologue.consent", stored);
      }, priorConsent);
      await page.reload();
      await expect(page.getByRole("region", { name: "Cookie consent" })).toBeVisible();
      expect(sdkRequests).toHaveLength(1);
      expect(ingestion).toHaveLength(stoppedAt);
      await attachArtifacts(testInfo, {
        name: "cross-origin-privacy-revoked",
        region: page.getByRole("region", { name: "Cookie consent" }),
        facts: { originalRevision, revision, ingestion, sdkRequests, recordingStopped: true },
      });
      await page
        .getByRole("region", { name: "Cookie consent" })
        .getByRole("button", { name: "Cool" })
        .click();
      await expect.poll(() => sdkRequests.length).toBe(2);
      await expect.poll(() => recordingStarted(page, sdkRequests[1])).toBe(true);
      expect(await captureBlocked(page, sdkRequests[1])).toBe(false);
      await expect
        .poll(() => ingestion.slice(stoppedAt).flatMap((request) => request.events))
        .toContain("privacy_revocation_probe");
      const freshConsent = await page.evaluate(() => localStorage.getItem("prologue.consent"));
      expect(JSON.parse(freshConsent ?? "null")).toEqual({ choice: "accepted", revision });
      const refreshed = stale.waitForEvent("framenavigated", {
        predicate: (frame) => frame === stale.mainFrame(),
        timeout: 10_000,
      });
      release();
      await refreshed;
      await stale.waitForLoadState("domcontentloaded");
      await expect.poll(() => recordingStarted(stale, sdkUrl)).toBe(true);
      await expect(stale.getByRole("region", { name: "Cookie consent" })).toBeHidden();
      expect(await stale.evaluate(() => localStorage.getItem("prologue.consent"))).toBe(
        freshConsent,
      );
      await attachArtifacts(testInfo, {
        name: "new-consent-survives-stale-tab",
        region: stale.getByRole("main"),
        facts: {
          originalRevision,
          revision,
          freshConsent: JSON.parse(freshConsent ?? "null"),
          ingestion,
        },
      });
    } finally {
      release();
      await stale.close();
      await root.close();
    }
  });
});

test.describe("Privacy revocation while the SDK is loading", () => {
  test.use({
    baseURL: "http://ludamus.localhost:8001",
    storageState: state("loading"),
    consentSeed: null,
  });

  test("a late SDK import cannot start capture after an age downgrade", async ({
    page,
    context,
  }, testInfo) => {
    const optionalRequests: string[] = [];
    await context.route("https://*.posthog.com/**", async (route) => {
      optionalRequests.push(route.request().url());
      await route.fulfill({ contentType: "application/json", body: "{}" });
    });
    let release = () => {};
    const released = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route(/module\.full\.no-external[^/]*\.js/u, async (route) => {
      await released;
      await route.continue();
    });
    const root = await context.newPage();
    try {
      await changeAge(root, "16 or older");
      await page.goto(SPHERE_URL);
      await expect(page.getByRole("button", { name: "Cookie settings" })).toBeVisible();
      const requested = page.waitForRequest((request) => isSdk(request.url()));
      await page
        .getByRole("region", { name: "Cookie consent" })
        .getByRole("button", { name: "Cool" })
        .click();
      const sdkUrl = (await requested).url();

      await changeAge(root, "13–15");
      await page.bringToFront();
      await expect
        .poll(() => page.evaluate(() => localStorage.getItem("prologue.consent")))
        .toBeNull();
      await expect(page.getByRole("button", { name: "Cookie settings" })).toBeHidden();
      release();
      await expect.poll(() => recordingStarted(page, sdkUrl)).toBe(false);

      expect(
        await page.evaluate(() => Object.keys(localStorage).some((key) => key.startsWith("ph_"))),
      ).toBe(false);
      expect(optionalRequests).toEqual([]);
      await attachArtifacts(testInfo, {
        name: "age-revoked-during-sdk-load",
        region: page.getByRole("main"),
        facts: { optionalRequests, recordingStarted: false, consent: null },
      });
    } finally {
      release();
      await root.close();
    }
  });
});

test.describe("Cookie cleanup without Cookie Store", () => {
  test.use({
    baseURL: "http://ludamus.localhost:8001",
    storageState: state("legacy"),
    consentSeed: null,
  });

  test("purges host and parent analytics cookies without fetching the SDK", async ({
    page,
    context,
  }, testInfo) => {
    const sdkRequests: string[] = [];
    page.on("request", (request) => {
      if (isSdk(request.url())) sdkRequests.push(request.url());
    });
    await context.addCookies([
      {
        name: "ph_host_posthog",
        value: "old-host-identity",
        domain: "another.ludamus.localhost",
        path: "/",
      },
      {
        name: "ph_parent_posthog",
        value: "old-parent-identity",
        domain: ".ludamus.localhost",
        path: "/",
      },
      { name: "__ph_opt_in_out_old", value: "1", domain: ".ludamus.localhost", path: "/" },
      { name: "unrelated", value: "keep-me", domain: ".ludamus.localhost", path: "/" },
    ]);
    await page.addInitScript(() => {
      Reflect.deleteProperty(window, "cookieStore");
      localStorage.setItem("prologue.consent", "accepted");
      localStorage.setItem("ph_old_posthog", "old-local-identity");
    });
    await page.goto(`${SPHERE_URL}crowd/profile/privacy/`);
    await expect(page.getByText(/Your age range is 13–15/u)).toBeVisible();
    expect(await page.evaluate(() => typeof window.cookieStore)).toBe("undefined");
    await expect
      .poll(() =>
        context
          .cookies()
          .then((cookies) =>
            cookies.filter(
              (cookie) =>
                cookie.name.startsWith("ph_") || cookie.name.startsWith("__ph_opt_in_out_"),
            ),
          ),
      )
      .toEqual([]);
    expect(
      await page.evaluate(() =>
        Object.keys(localStorage).filter(
          (key) => key === "prologue.consent" || key.startsWith("ph_"),
        ),
      ),
    ).toEqual([]);
    expect(
      await context
        .cookies()
        .then((cookies) => cookies.find((cookie) => cookie.name === "unrelated")?.value),
    ).toBe("keep-me");
    expect(sdkRequests).toEqual([]);
    await attachArtifacts(testInfo, {
      name: "legacy-cookie-cleanup",
      region: page.getByRole("main"),
      facts: { sdkRequests, unrelatedCookie: "keep-me", cookieStoreAvailable: false },
    });
  });
});
