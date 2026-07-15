import type {
  AgentDeviceClient,
  AgentDeviceSelectionOptions,
  CaptureSnapshotResult,
} from "agent-device";

import { beforeAll, expect, test } from "bun:test";
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { pathToFileURL } from "node:url";

type AgentDeviceModule = typeof import("agent-device");

type IosDeviceOptions = AgentDeviceSelectionOptions & {
  platform: "ios";
};

const env = process.env;
const baseUrl = env.BASE_URL ?? "http://localhost:8000";
const session = env.SESSION ? `${env.SESSION}-scrubber` : "zagrajmy-ios-scrubber-local";
const eventPath = env.EVENT_PATH ?? "/chronology/event/kapitularz-2025-anonymized/";
const deviceName = env.IOS_DEVICE_NAME ?? "iPhone 16";
const runtime = env.IOS_RUNTIME;
const providedUdid = env.UDID;
const hookTimeoutMs = Number(env.IOS_HOOK_TIMEOUT_MS ?? "240000");

const calloutSignals = [
  "Hide preview",
  "Open in New Tab",
  "Open in Tab Group",
  "Add to Reading List",
  "Download Linked File",
];

const importAgentDevice = async (): Promise<AgentDeviceModule> => {
  try {
    return await import("agent-device");
  } catch (error) {
    const candidates: string[] = [];
    try {
      const npmRoot = execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim();
      candidates.push(`${npmRoot}/agent-device/dist/src/index.js`);
    } catch {}
    if (env.HOME) {
      candidates.push(
        `${env.HOME}/.bun/install/global/node_modules/agent-device/dist/src/index.js`,
      );
    }
    for (const candidate of candidates) {
      if (existsSync(candidate)) {
        return (await import(pathToFileURL(candidate).href)) as AgentDeviceModule;
      }
    }
    throw error;
  }
};

const { createAgentDeviceClient } = await importAgentDevice();
const client: AgentDeviceClient = createAgentDeviceClient({ session });

const deviceOptions: IosDeviceOptions = providedUdid
  ? { platform: "ios", udid: providedUdid }
  : { platform: "ios", device: deviceName };

const ensureSimulator = async (): Promise<string> => {
  if (providedUdid) return providedUdid;

  const result = await client.simulators.ensure({
    device: deviceName,
    ...(runtime ? { runtime } : {}),
    boot: true,
    reuseExisting: true,
  });
  return result.udid;
};

const takeSnapshot = async (): Promise<CaptureSnapshotResult> =>
  client.capture.snapshot({ ...deviceOptions, interactiveOnly: true });

const snapshotLabels = async (): Promise<string[]> => {
  const snapshot = await takeSnapshot();
  return snapshot.nodes.map((node) => node.label ?? node.value ?? "").filter(Boolean);
};

const openUrlWithSafari = async (url: string): Promise<void> => {
  try {
    await client.apps.open({ ...deviceOptions, app: "Safari", url });
  } catch (error) {
    console.warn(
      "Safari reported a URL open failure; continuing because iOS Simulator can time out after Safari has already loaded the page.",
      error,
    );
  }
};

const openUrl = async (url: string, udid: string): Promise<void> => {
  if (!providedUdid) {
    await openUrlWithSafari(url);
    return;
  }
  try {
    execFileSync("xcrun", ["simctl", "openurl", udid, url], { stdio: "inherit", timeout: 10000 });
  } catch (error) {
    console.warn(
      "simctl reported a URL open failure; continuing because iOS Simulator can time out before Safari finishes loading.",
      error,
    );
  }
  await openUrlWithSafari(url);
};

type Rect = { x: number; y: number; width: number; height: number };

const viewportRect = async (): Promise<Rect> =>
  (await takeSnapshot()).nodes[0]?.rect ?? { x: 0, y: 0, width: 402, height: 874 };

const scrollScheduleIntoView = async (): Promise<void> => {
  for (let attempt = 0; attempt < 14; attempt += 1) {
    const snapshot = await takeSnapshot();
    const viewportHeight = snapshot.nodes[0]?.rect?.height ?? 874;
    const sessionOnScreen = snapshot.nodes.some(
      (node) =>
        (node.label ?? "").startsWith("Open details for") &&
        node.rect !== undefined &&
        node.rect.y > 80 &&
        node.rect.y < viewportHeight - 120,
    );
    if (sessionOnScreen) return;
    await client.interactions.scroll({ ...deviceOptions, direction: "down", pixels: 450 });
    await client.command.wait({ ...deviceOptions, durationMs: 300 });
  }
};

const closeSessionIfPresent = async (name: string): Promise<void> => {
  try {
    const sessions = await client.sessions.list();
    if (!sessions.some((activeSession) => activeSession.name === name)) return;

    console.log(`Taking over existing agent-device session: ${name}`);
    await client.sessions.close({ session: name });
  } catch (error) {
    console.warn(`Could not check or close existing session ${name}:`, error);
  }
};

const closeDeviceSessionIfPresent = async (): Promise<void> => {
  try {
    const sessions = await client.sessions.list();
    const activeSession = sessions.find((candidate) => {
      if (providedUdid) return candidate.device.ios?.udid === providedUdid;
      return candidate.device.name === deviceName && candidate.device.platform === "ios";
    });
    if (!activeSession || activeSession.name === session) return;

    console.log(`Taking over iOS device from existing agent-device session: ${activeSession.name}`);
    await client.sessions.close({ session: activeSession.name });
  } catch (error) {
    console.warn("Could not check or close existing device session:", error);
  }
};

const assertEventPageReady = async (url: URL): Promise<void> => {
  console.log(`Checking local event page at ${url.toString()}...`);
  const deadline = Date.now() + 60000;
  let lastError = "no response";

  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      const text = await response.text();
      if (response.ok && text.includes("schedule-rail")) return;

      lastError = `HTTP ${response.status}; body starts with ${JSON.stringify(text.slice(0, 160))}`;
      if (response.status >= 400 && response.status < 500) break;
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }

  throw new Error(
    `Local event page is not usable at ${url.toString()} (${lastError}). ` +
      "Make sure the e2e server is running and serving the seeded dense schedule.",
  );
};

const eventUrl = new URL(eventPath, baseUrl);

let surfacedCalloutSignals: string[] = [];

beforeAll(async () => {
  await assertEventPageReady(eventUrl);
  await closeSessionIfPresent(session);
  await closeDeviceSessionIfPresent();

  console.log(`Preparing iOS simulator ${providedUdid ?? deviceName}...`);
  const udid = await ensureSimulator();
  console.log(`Using simulator UDID: ${udid}`);

  console.log(`Opening Safari at ${eventUrl.toString()}...`);
  await openUrl(eventUrl.toString(), udid);
  await client.command.wait({ ...deviceOptions, durationMs: 3000 });

  await scrollScheduleIntoView();

  const viewport = await viewportRect();
  const x = viewport.x + viewport.width - 4;
  const fractions = [0.3, 0.45, 0.6, 0.75];
  for (const fraction of fractions) {
    const y = viewport.y + viewport.height * fraction;
    console.log(`Long-pressing the rail at x=${Math.round(x)} y=${Math.round(y)}...`);
    await client.interactions.longPress({ ...deviceOptions, x, y, durationMs: 800 });
    await client.command.wait({ ...deviceOptions, durationMs: 900 });
    const labels = await snapshotLabels();
    const surfaced = calloutSignals.filter((signal) =>
      labels.some((label) => label.includes(signal)),
    );
    if (surfaced.length > 0) {
      surfacedCalloutSignals = surfaced;
      break;
    }
  }
}, hookTimeoutMs);

test("long-pressing the hour rail does not open the iOS link callout", () => {
  expect(surfacedCalloutSignals).toEqual([]);
});
