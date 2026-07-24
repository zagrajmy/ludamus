import type {
  AgentDeviceClient,
  AgentDeviceSelectionOptions,
  AgentDeviceSession,
  CaptureSnapshotResult,
  SnapshotNode,
} from "agent-device";

import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { pathToFileURL } from "node:url";

type AgentDeviceModule = typeof import("agent-device");
type IosDeviceOptions = AgentDeviceSelectionOptions & { platform: "ios" };

const env = process.env;

export const baseUrl = env.BASE_URL ?? "http://localhost:8000";
export const hookTimeoutMs = Number(env.IOS_HOOK_TIMEOUT_MS ?? "240000");

const deviceName = env.IOS_DEVICE_NAME ?? "iPhone 16";
const runtime = env.IOS_RUNTIME;
const providedUdid = env.UDID;

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

export type IosHarness = {
  client: AgentDeviceClient;
  deviceOptions: IosDeviceOptions;
  takeSnapshot: () => Promise<CaptureSnapshotResult>;
  snapshotLabels: () => Promise<string[]>;
  findNodeByLabel: (label: string) => Promise<SnapshotNode | null>;
  wait: (durationMs: number) => Promise<void>;
  openUrl: (url: string, udid: string) => Promise<void>;
  prepareDevice: () => Promise<string>;
  assertPageReady: (url: URL, contains: string) => Promise<void>;
};

export const createIosHarness = async (session: string): Promise<IosHarness> => {
  const { createAgentDeviceClient, isAgentDeviceError } = await importAgentDevice();
  const client: AgentDeviceClient = createAgentDeviceClient({ session });

  const deviceOptions: IosDeviceOptions = providedUdid
    ? { platform: "ios", udid: providedUdid }
    : { platform: "ios", device: deviceName };

  const takeSnapshot = (): Promise<CaptureSnapshotResult> =>
    client.capture.snapshot({ ...deviceOptions, interactiveOnly: true });

  const snapshotLabels = async (): Promise<string[]> => {
    const snapshot = await takeSnapshot();
    return snapshot.nodes.map((node) => node.label ?? node.value ?? "").filter(Boolean);
  };

  const findNodeByLabel = async (label: string): Promise<SnapshotNode | null> => {
    const snapshot = await takeSnapshot();
    return snapshot.nodes.find((node) => node.label === label) ?? null;
  };

  const wait = (durationMs: number): Promise<void> =>
    client.command.wait({ ...deviceOptions, durationMs }).then(() => undefined);

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

  const openUrlWithSafari = async (url: string): Promise<void> => {
    try {
      await client.apps.open({ ...deviceOptions, app: "Safari", url });
    } catch (error) {
      if (isAgentDeviceError(error) && error.code === "DEVICE_IN_USE") throw error;
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

  const closeSessionIfPresent = async (): Promise<void> => {
    try {
      const sessions = await client.sessions.list();
      if (!sessions.some((activeSession) => activeSession.name === session)) return;

      console.log(`Taking over existing agent-device session: ${session}`);
      await client.sessions.close({ session });
    } catch (error) {
      console.warn(`Could not check or close existing session ${session}:`, error);
    }
  };

  const findConflictingSession = (sessions: AgentDeviceSession[]): AgentDeviceSession | null => {
    const holder = sessions.find((candidate) => {
      if (providedUdid) return candidate.device.ios?.udid === providedUdid;
      return candidate.device.name === deviceName && candidate.device.platform === "ios";
    });
    return holder && holder.name !== session ? holder : null;
  };

  const closeDeviceSessionIfPresent = async (): Promise<void> => {
    try {
      const activeSession = findConflictingSession(await client.sessions.list());
      if (!activeSession) return;

      console.log(
        `Taking over iOS device from existing agent-device session: ${activeSession.name}`,
      );
      await client.sessions.close({ session: activeSession.name });

      const deadline = Date.now() + 15000;
      while (Date.now() < deadline) {
        if (!findConflictingSession(await client.sessions.list())) return;
        await new Promise((resolve) => setTimeout(resolve, 500));
      }
      console.warn(
        `Session ${activeSession.name} still holds the device 15s after close; proceeding anyway.`,
      );
    } catch (error) {
      console.warn("Could not check or close existing device session:", error);
    }
  };

  const prepareDevice = async (): Promise<string> => {
    await closeSessionIfPresent();
    await closeDeviceSessionIfPresent();
    console.log(`Preparing iOS simulator ${providedUdid ?? deviceName}...`);
    const udid = await ensureSimulator();
    console.log(`Using simulator UDID: ${udid}`);
    return udid;
  };

  const assertPageReady = async (url: URL, contains: string): Promise<void> => {
    console.log(`Checking local event page at ${url.toString()}...`);
    const deadline = Date.now() + 60000;
    let lastError = "no response";

    while (Date.now() < deadline) {
      try {
        const response = await fetch(url);
        const text = await response.text();
        if (response.ok && text.includes(contains)) return;

        lastError = `HTTP ${response.status}; body starts with ${JSON.stringify(text.slice(0, 160))}`;
        if (response.status >= 400 && response.status < 500) break;
      } catch (error) {
        lastError = error instanceof Error ? error.message : String(error);
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }

    throw new Error(
      `Local event page is not usable at ${url.toString()} (${lastError}). ` +
        "Make sure the e2e server is running and serving the seeded event.",
    );
  };

  return {
    client,
    deviceOptions,
    takeSnapshot,
    snapshotLabels,
    findNodeByLabel,
    wait,
    openUrl,
    prepareDevice,
    assertPageReady,
  };
};
