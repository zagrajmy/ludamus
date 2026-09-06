import type {
  AgentDeviceClient,
  AgentDeviceSelectionOptions,
  AgentDeviceSession,
  CaptureSnapshotResult,
  SnapshotNode,
} from "agent-device";

import { createAgentDeviceClient, isAgentDeviceError } from "agent-device";

import { collapse, labelOf, matchesScopeLabel, pollUntil } from "./snapshot";

type IosDeviceOptions = AgentDeviceSelectionOptions & { platform: "ios" };

const env = process.env;

export const baseUrl = env.BASE_URL ?? "http://localhost:8000";

export const resolveEventUrl = (defaultPath: string): URL =>
  new URL(env.EVENT_PATH ?? defaultPath, baseUrl);

export const sessionName = (role: string): string =>
  env.SESSION ? `${env.SESSION}-${role}` : `zagrajmy-ios-${role}-local`;

// SAFETY: NaN or Infinity would make pollUntil's deadline comparison never true
// and a hook timeout undefined, so a typo'd override spins silently until the
// job's own timeout kills it.
export const positiveMs = (name: string, fallback: number): number => {
  const raw = env[name];
  const value = raw === undefined ? fallback : Number(raw);
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error(
      `${name} must be a positive number of milliseconds; got ${JSON.stringify(raw)}`,
    );
  }
  return value;
};

// NOTE: the default only applies to local runs, where nothing has paid the
// XCUITest runner's build yet -- run warmup.ts first, or raise it.
export const hookTimeoutMs = positiveMs("IOS_HOOK_TIMEOUT_MS", 300000);

const deviceName = env.IOS_DEVICE_NAME ?? "iPhone 17 Pro";
const runtime = env.IOS_RUNTIME;
const providedUdid = env.UDID;
const safariReadyTimeoutMs = positiveMs("IOS_SAFARI_READY_TIMEOUT_MS", 60000);

export type SafariReadiness = {
  expectedLabels: readonly string[];
  match?: "all" | "any";
  scope?: string;
};

export type IosHarness = {
  client: AgentDeviceClient;
  deviceOptions: IosDeviceOptions;
  takeSnapshot: (scope?: string) => Promise<CaptureSnapshotResult>;
  close: () => Promise<void>;
  snapshotLabels: (scope?: string) => Promise<string[]>;
  findNodeByLabel: (label: string) => Promise<SnapshotNode | null>;
  wait: (durationMs: number) => Promise<void>;
  openUrl: (url: string, readiness: SafariReadiness) => Promise<void>;
  prepareDevice: () => Promise<void>;
};

export const createIosHarness = (session: string): IosHarness => {
  const client: AgentDeviceClient = createAgentDeviceClient({ session });

  const deviceOptions: IosDeviceOptions = providedUdid
    ? { platform: "ios", udid: providedUdid }
    : { platform: "ios", device: deviceName };

  // NOTE: the runner walks at most 300 nodes per snapshot and silently drops
  // the rest (`fastSnapshotLimit`, surfaced as `truncated`), so on a large page
  // anything late in document order never appears. `scope` narrows the walk to
  // the subtree of the first element whose accessible label or identifier
  // contains the given text -- resolved by a live element query, which has no
  // such cap. A scope that matches nothing falls back to the full, possibly
  // truncated, tree.
  const takeSnapshot = (scope?: string): Promise<CaptureSnapshotResult> =>
    client.capture.snapshot({
      ...deviceOptions,
      interactiveOnly: true,
      ...(scope ? { scope } : {}),
    });

  const snapshotLabels = async (scope?: string): Promise<string[]> => {
    const snapshot = await takeSnapshot(scope);
    return snapshot.nodes.map(labelOf).filter(Boolean);
  };

  const close = async (): Promise<void> => {
    try {
      await client.sessions.close({ session });
    } catch (error) {
      console.warn(`Could not close session ${session}:`, error);
    }
  };

  const findNodeByLabel = async (label: string): Promise<SnapshotNode | null> => {
    const snapshot = await takeSnapshot();
    const wanted = collapse(label);
    return snapshot.nodes.find((node) => labelOf(node) === wanted) ?? null;
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

  // Hands back the failure rather than throwing it: an open that reports an
  // error can still complete late, so the snapshot decides, not this call.
  const openSafari = async (url: string): Promise<unknown> => {
    try {
      await client.apps.open({ ...deviceOptions, app: "Safari", url });
      return null;
    } catch (error) {
      if (isAgentDeviceError(error) && error.code === "DEVICE_IN_USE") throw error;
      console.warn("Safari open reported an error; checking whether it completed late.", error);
      return error;
    }
  };

  // Two passes, re-opening between them. Warmup and a previous spec both leave
  // Safari frontmost, so "the open did not take" looks like Safari sitting on
  // the wrong page, not like Safari being absent -- the only condition worth
  // retrying on is the page still not being ready. Re-opening the same URL
  // re-applies the same fragment, which is what a caller waiting on one wants.
  const openUrl = async (url: string, readiness: SafariReadiness): Promise<void> => {
    const { expectedLabels, match = "all" } = readiness;
    // Collapsed here rather than at the callers: the scope is matched against
    // labels that already went through labelOf, and the runner's element query
    // sees the device's own collapsed name too.
    const scope = readiness.scope === undefined ? undefined : collapse(readiness.scope);
    if (expectedLabels.length === 0) {
      throw new Error(`openUrl needs at least one expected label to wait for at ${url}.`);
    }
    const expected = expectedLabels.map(collapse);
    const startedAt = Date.now();
    let observed = "no snapshot completed";

    const probe = async (): Promise<CaptureSnapshotResult | null> => {
      try {
        const snapshot = await takeSnapshot(scope);
        const app = snapshot.appBundleId ?? snapshot.appName ?? "an unknown app";
        const labels = snapshot.nodes.map(labelOf);
        const scopeMatched = !scope || labels.some((label) => matchesScopeLabel(label, scope));
        const contentMatched =
          match === "all"
            ? expected.every((label) => labels.includes(label))
            : expected.some((label) => labels.includes(label));
        observed = `app=${app}; scopeMatched=${String(scopeMatched)}; labels=${JSON.stringify(labels.slice(0, 20))}`;
        return snapshot.appBundleId === "com.apple.mobilesafari" && scopeMatched && contentMatched
          ? snapshot
          : null;
      } catch (error) {
        if (isAgentDeviceError(error) && error.code === "DEVICE_IN_USE") throw error;
        observed = error instanceof Error ? error.message : String(error);
        return null;
      }
    };

    // SAFETY: the window bounds how long polling continues, never how long one
    // probe may take -- pollUntil hands back a result that lands after the
    // deadline. The first probe is this session's first runner-backed command,
    // so it pays the XCUITest launch (125-148s in the daemon log) whatever the
    // window says; taking it outside the loop leaves the window sizing the
    // thing it can actually size, a page load.
    let openError = await openSafari(url);
    let ready = await probe();
    ready ??= await pollUntil(probe, { timeoutMs: safariReadyTimeoutMs, intervalMs: 1000 });
    if (!ready) {
      openError = (await openSafari(url)) ?? openError;
      ready = await pollUntil(probe, { timeoutMs: safariReadyTimeoutMs, intervalMs: 1000 });
    }

    if (!ready) {
      throw new Error(
        `Safari did not load ${JSON.stringify(expected)} at ${url} after ` +
          `${Date.now() - startedAt}ms over two opens; last observation: ${observed}`,
        { cause: openError },
      );
    }
  };

  const prepareDevice = async (): Promise<void> => {
    await closeSessionIfPresent();
    await closeDeviceSessionIfPresent();
    console.log(`Preparing iOS simulator ${providedUdid ?? deviceName}...`);
    const udid = await ensureSimulator();
    console.log(`Using simulator UDID: ${udid}`);
  };

  return {
    client,
    deviceOptions,
    takeSnapshot,
    close,
    snapshotLabels,
    findNodeByLabel,
    wait,
    openUrl,
    prepareDevice,
  };
};
