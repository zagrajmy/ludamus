import type {
  AgentDeviceClient,
  AgentDeviceSelectionOptions,
  AgentDeviceSession,
  CaptureSnapshotResult,
  SnapshotNode,
} from "agent-device";

import { createAgentDeviceClient, isAgentDeviceError } from "agent-device";
import { execFileSync } from "node:child_process";

type IosDeviceOptions = AgentDeviceSelectionOptions & { platform: "ios" };

const env = process.env;

export const baseUrl = env.BASE_URL ?? "http://localhost:8000";

export const sessionName = (role: string): string =>
  env.SESSION ? `${env.SESSION}-${role}` : `zagrajmy-ios-${role}-local`;

// The workflow sets this per attempt. The default only applies to local runs,
// where nothing has paid the 194-240s cold runner attach yet -- run
// `bun run scripts/ios-regressions/warmup.ts` first, or raise it.
export const hookTimeoutMs = Number(env.IOS_HOOK_TIMEOUT_MS ?? "300000");

export type Rect = { x: number; y: number; width: number; height: number };

// Only reached when a snapshot comes back with no nodes to read a rect from. Sized for the iPhone 17 Pro the workflow asks for first;
// when the image lacks that device the workflow picks another, so treat this as
// a shape that keeps arithmetic finite, not as this run's screen.
const FALLBACK_VIEWPORT: Rect = { x: 0, y: 0, width: 402, height: 874 };

const deviceName = env.IOS_DEVICE_NAME ?? "iPhone 17 Pro";
const runtime = env.IOS_RUNTIME;
const providedUdid = env.UDID;

// One convention for "is this on screen": rect centre inside the viewport,
// clear of a band for Safari's top and bottom chrome. The band's exact size is
// unknowable from this sandbox; being conservative only narrows what counts as
// visible, which specs must treat as "press/check something else", never as a
// pass. The runner's `hittable` is NOT this check — it reads false inside
// Safari's web content (device-falsified on this branch).
const CHROME_INSET = 120;

export const centreOnScreen = (rect: Rect, viewport: Rect): boolean => {
  const centreY = rect.y + rect.height / 2;
  return (
    centreY >= viewport.y + CHROME_INSET && centreY <= viewport.y + viewport.height - CHROME_INSET
  );
};

export const describeNode = (node: SnapshotNode): string => {
  const rect = node.rect
    ? ` x=${Math.round(node.rect.x)} y=${Math.round(node.rect.y)} w=${Math.round(node.rect.width)} h=${Math.round(node.rect.height)}`
    : "";
  return `${node.type ?? "node"} ref=@${node.ref}${rect} hittable=${String(node.hittable)} label=${JSON.stringify(
    node.label ?? node.value ?? "",
  )}`;
};

export type IosHarness = {
  client: AgentDeviceClient;
  deviceOptions: IosDeviceOptions;
  takeSnapshot: () => Promise<CaptureSnapshotResult>;
  viewportOf: (snapshot: CaptureSnapshotResult) => Rect;
  close: () => Promise<void>;
  snapshotLabels: () => Promise<string[]>;
  findNodeByLabel: (label: string) => Promise<SnapshotNode | null>;
  wait: (durationMs: number) => Promise<void>;
  openUrl: (url: string, udid: string) => Promise<void>;
  prepareDevice: () => Promise<string>;
  fetchReadyPage: (url: URL, contains: string) => Promise<string>;
};

export const createIosHarness = (session: string): IosHarness => {
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

  const viewportOf = (snapshot: CaptureSnapshotResult): Rect =>
    snapshot.nodes[0]?.rect ?? FALLBACK_VIEWPORT;

  const close = async (): Promise<void> => {
    try {
      await client.sessions.close({ session });
    } catch (error) {
      console.warn(`Could not close session ${session}:`, error);
    }
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

  // Waits for the page to serve `contains`, then hands back the body. A caller
  // that needs a landmark from the markup -- a scrubber slot anchor, the
  // accessible name of a control -- reads it here instead of hunting for it
  // with gestures, which are the slowest thing either spec can do.
  const fetchReadyPage = async (url: URL, contains: string): Promise<string> => {
    console.log(`Checking local event page at ${url.toString()}...`);
    const deadline = Date.now() + 60000;
    let lastError = "no response";

    // Pin the language both halves of a spec see. Bun's fetch sends no
    // Accept-Language, so Django falls back to LANGUAGE_CODE ("pl") and dates
    // render from Django's own compiled catalogue — "Sobota" — while the
    // en-US simulator's Safari asks for and gets "Saturday". Names read from
    // this HTML then never match device labels. Pinning "en" aligns the two;
    // if the simulator is ever not English, set-membership finds nothing and
    // the spec fails loudly rather than passing vacuously.
    const headers = { "Accept-Language": "en" };

    while (Date.now() < deadline) {
      try {
        const response = await fetch(url, { headers });
        const text = await response.text();
        if (response.ok && text.includes(contains)) return text;

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
    viewportOf,
    close,
    snapshotLabels,
    findNodeByLabel,
    wait,
    openUrl,
    prepareDevice,
    fetchReadyPage,
  };
};
