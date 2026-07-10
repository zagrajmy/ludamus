#!/usr/bin/env bun

import type {
  AgentDeviceClient,
  AgentDeviceSelectionOptions,
  CaptureSnapshotResult,
  SnapshotNode,
} from "agent-device";

import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { pathToFileURL } from "node:url";

type AgentDeviceModule = typeof import("agent-device");

type IosDeviceOptions = AgentDeviceSelectionOptions & {
  platform: "ios";
};

const env = process.env;
const baseUrl = env.BASE_URL ?? "http://localhost:8000";
const session = env.SESSION ?? "zagrajmy-ios-modal-local";
const targetTitle = env.TARGET_SESSION_TITLE ?? "Przygoda w Mieście Neonów";
const targetTriggerLabel = env.TARGET_TRIGGER_LABEL ?? `Open details for ${targetTitle}`;
const eventPath = env.EVENT_PATH ?? "/event/autumn-open/";
const targetQueryParam = env.TARGET_QUERY_PARAM ?? "session=3";
const deviceName = env.IOS_DEVICE_NAME ?? "iPhone 16";
const runtime = env.IOS_RUNTIME;
const providedUdid = env.UDID;

const importAgentDevice = async (): Promise<AgentDeviceModule> => {
  try {
    return await import("agent-device");
  } catch (error) {
    const candidates: string[] = [];
    try {
      const npmRoot = execFileSync("npm", ["root", "-g"], {
        encoding: "utf8",
      }).trim();
      candidates.push(`${npmRoot}/agent-device/dist/src/index.js`);
    } catch {
      // Ignore and try Bun's global install path below.
    }
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
  client.capture.snapshot({
    ...deviceOptions,
    interactiveOnly: true,
  });

const snapshotLabels = async (): Promise<string[]> => {
  const snapshot = await takeSnapshot();
  return snapshot.nodes.map((node) => node.label ?? node.value ?? "").filter(Boolean);
};

const hasVisibleText = async (text: string): Promise<boolean> => {
  const labels = await snapshotLabels();
  return labels.some((label) => label.includes(text));
};

const findNodeByLabel = async (label: string): Promise<SnapshotNode | null> => {
  const snapshot = await takeSnapshot();
  return snapshot.nodes.find((node) => node.label === label) ?? null;
};

const openUrlWithSafari = async (url: string): Promise<void> => {
  try {
    await client.apps.open({
      ...deviceOptions,
      app: "Safari",
      url,
    });
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
    execFileSync("xcrun", ["simctl", "openurl", udid, url], {
      stdio: "inherit",
      timeout: 10000,
    });
  } catch (error) {
    console.warn(
      "simctl reported a URL open failure; continuing because iOS Simulator can time out before Safari finishes loading.",
      error,
    );
  }

  await openUrlWithSafari(url);
};

const clickNodeCenter = async (node: SnapshotNode): Promise<void> => {
  if (node.rect) {
    await client.interactions.click({
      ...deviceOptions,
      x: node.rect.x + node.rect.width / 2,
      y: node.rect.y + node.rect.height / 2,
    });
    return;
  }

  await client.interactions.click({ ...deviceOptions, ref: `@${node.ref}` });
};

const clickNodeReference = async (node: SnapshotNode): Promise<void> => {
  await client.interactions.click({ ...deviceOptions, ref: `@${node.ref}` });
};

const describeNode = (node: SnapshotNode): string => {
  const rect = node.rect
    ? ` x=${Math.round(node.rect.x)} y=${Math.round(node.rect.y)} w=${Math.round(node.rect.width)} h=${Math.round(node.rect.height)}`
    : "";
  return `${node.type ?? "node"} ref=@${node.ref}${rect} label=${JSON.stringify(
    node.label ?? node.value ?? "",
  )}`;
};

const isNodeInViewport = (snapshot: CaptureSnapshotResult, node: SnapshotNode): boolean => {
  if (!node.rect) return false;
  const viewportHeight = snapshot.nodes[0]?.rect?.height ?? 852;
  const centerY = node.rect.y + node.rect.height / 2;
  return centerY >= 80 && centerY <= viewportHeight - 120;
};

const isHiddenDialogLabel = (node: SnapshotNode): boolean =>
  (node.label ?? "").includes("web dialog");

const isTargetTitleNode = (node: SnapshotNode): boolean =>
  Boolean(node.label?.includes(targetTitle)) && !isHiddenDialogLabel(node);

const findTriggerInViewport = (snapshot: CaptureSnapshotResult): SnapshotNode | null =>
  snapshot.nodes.find(
    (node) =>
      node.label === targetTriggerLabel &&
      !isHiddenDialogLabel(node) &&
      isNodeInViewport(snapshot, node),
  ) ?? null;

const findTargetTitleInViewport = (snapshot: CaptureSnapshotResult): SnapshotNode | null =>
  snapshot.nodes.find((node) => isTargetTitleNode(node) && isNodeInViewport(snapshot, node)) ??
  null;

const scrollUntilTriggerInViewport = async (): Promise<SnapshotNode> => {
  for (let attempt = 0; attempt < 16; attempt += 1) {
    const snapshot = await takeSnapshot();
    const trigger = findTriggerInViewport(snapshot);
    if (trigger) return trigger;

    const visibleTitle = findTargetTitleInViewport(snapshot);
    if (visibleTitle) {
      console.warn(
        `The target session title is visible but the link ${JSON.stringify(
          targetTriggerLabel,
        )} is not in the accessibility snapshot; falling back to the visible title node.`,
      );
      return visibleTitle;
    }

    const node =
      snapshot.nodes.find(
        (candidate) => candidate.label === targetTriggerLabel && !isHiddenDialogLabel(candidate),
      ) ?? snapshot.nodes.find(isTargetTitleNode);
    const viewportHeight = snapshot.nodes[0]?.rect?.height ?? 852;
    const centerY = node?.rect ? node.rect.y + node.rect.height / 2 : viewportHeight;
    await client.interactions.scroll({
      ...deviceOptions,
      direction: centerY > viewportHeight - 120 ? "down" : "up",
      pixels: 450,
    });
    await client.command.wait({ ...deviceOptions, durationMs: 200 });
  }

  throw new Error(`Could not bring ${targetTriggerLabel} into the viewport`);
};

// Force a substantial page scroll before opening the modal. The iOS top-layer
// hit-testing offset this script guards against only manifests when the modal
// is opened over a *scrolled* document, so the regression silently stops being
// exercised whenever the seeded page is short enough to fit the trigger above
// the fold. Scrolling down a fixed number of steps first guarantees a
// meaningful document offset independent of how tall the seed data renders.
const preOpenScrollSteps = Number(env.PRE_OPEN_SCROLL_STEPS ?? "8");

const forcePreOpenScroll = async (): Promise<void> => {
  for (let step = 0; step < preOpenScrollSteps; step += 1) {
    await client.interactions.scroll({
      ...deviceOptions,
      direction: "down",
      pixels: 450,
    });
    await client.command.wait({ ...deviceOptions, durationMs: 150 });
  }
};

const waitForLabel = async (label: string, timeoutMs: number): Promise<SnapshotNode | null> => {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const node = await findNodeByLabel(label);
    if (node) return node;
    await client.command.wait({ ...deviceOptions, durationMs: 500 });
  }
  return null;
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
      if (response.ok && text.includes(targetTitle)) return;

      lastError = `HTTP ${response.status}; body starts with ${JSON.stringify(text.slice(0, 160))}`;
      if (response.status >= 400 && response.status < 500) break;
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }

    await new Promise((resolve) => setTimeout(resolve, 1000));
  }

  throw new Error(
    `Local event page is not usable at ${url.toString()} (${lastError}). ` +
      `Make sure the e2e server is running and serving seeded data for ${targetTitle}.`,
  );
};

const eventUrl = new URL(eventPath, baseUrl);
const modalUrl = new URL(eventUrl);
for (const [key, value] of new URLSearchParams(targetQueryParam)) {
  modalUrl.searchParams.set(key, value);
}

const failures: string[] = [];

await assertEventPageReady(eventUrl);
await closeSessionIfPresent(session);
await closeDeviceSessionIfPresent();

console.log(`Preparing iOS simulator ${providedUdid ?? deviceName}...`);
const udid = await ensureSimulator();
console.log(`Using simulator UDID: ${udid}`);

const openViaScrolledPage = env.OPEN_VIA_SCROLLED_PAGE !== "0";
const initialUrl = openViaScrolledPage ? eventUrl : modalUrl;
console.log(`Opening Safari at ${initialUrl.toString()}...`);
await openUrl(initialUrl.toString(), udid);

await client.command.wait({ ...deviceOptions, durationMs: 3000 });

// Captured just before opening so the close path can assert the page returned
// to the same scroll position (see the scroll-preservation check after close).
let preOpenTriggerLabel: string | null = null;
let preOpenTriggerY: number | null = null;

if (openViaScrolledPage) {
  console.log(`Opening ${targetTitle} from a scrolled page...`);
  console.log(`Pre-scrolling the page (${preOpenScrollSteps} steps) before opening...`);
  await forcePreOpenScroll();
  const trigger = await scrollUntilTriggerInViewport();
  console.log(`Activating modal trigger: ${describeNode(trigger)}`);
  preOpenTriggerLabel = trigger.label ?? null;
  preOpenTriggerY = trigger.rect?.y ?? null;
  await clickNodeReference(trigger);
  if (!(await waitForLabel("Close", 5000))) {
    console.warn("The trigger reference did not open the modal; tapping its center.");
    await clickNodeCenter(trigger);
  }
} else {
  console.log(`Waiting for ${targetTitle} details...`);
}

const visibleCloseButton = await waitForLabel("Close", 15000);
if (!visibleCloseButton) {
  const labels = (await snapshotLabels()).slice(0, 40).join(" | ");
  throw new Error(
    `The modal did not open: Close button was not visible. Snapshot labels: ${labels}`,
  );
}

console.log("Checking whether modal content is initially visible...");
const contentInitiallyVisible =
  (await hasVisibleText("About this session")) && (await hasVisibleText("Przygoda w stylu filmu"));
if (!contentInitiallyVisible) {
  failures.push(
    'Modal content headed by "About this session" / "Przygoda w stylu filmu" is not initially visible.',
  );
}

console.log("Tapping Close...");
const closeButton = await findNodeByLabel("Close");
if (!closeButton) {
  throw new Error("Could not find visible target: Close");
}
await clickNodeCenter(closeButton);
await client.command.wait({ ...deviceOptions, durationMs: 1000 });

if (await hasVisibleText("Close")) {
  failures.push("The modal X / Close button did not close the modal.");
}

// Scroll-preservation guard. While the modal is open the page is scroll-locked
// by pinning <body> with `position: fixed; top: -scrollY` (needed so the iOS
// top-layer Close button stays tappable over a scrolled page). The close must
// hand the document back to that same offset; if it restores late or to the
// wrong place, the page jumps — most visibly to the top and back on Mobile
// Safari. Re-find the trigger we opened from and assert it settled back to the
// viewport position it held before opening.
if (openViaScrolledPage && preOpenTriggerLabel && preOpenTriggerY !== null) {
  await client.command.wait({ ...deviceOptions, durationMs: 600 });
  const settledSnapshot = await takeSnapshot();
  const settledTrigger = settledSnapshot.nodes.find(
    (node) => node.label === preOpenTriggerLabel && !isHiddenDialogLabel(node),
  );
  const settledY = settledTrigger?.rect?.y ?? null;
  if (settledY === null) {
    failures.push(
      `After closing, "${preOpenTriggerLabel}" was no longer in the viewport, ` +
        "so the page did not return to its pre-open scroll position.",
    );
  } else if (Math.abs(settledY - preOpenTriggerY) > 200) {
    failures.push(
      `The page scroll jumped on close: "${preOpenTriggerLabel}" moved from ` +
        `y=${Math.round(preOpenTriggerY)} to y=${Math.round(settledY)} ` +
        "(>200px), so the scroll position was not preserved.",
    );
  }
}

if (failures.length > 0) {
  console.error("\nReproduced iOS modal bug(s):");
  for (const failure of failures) {
    console.error(`- ${failure}`);
  }
  process.exitCode = 1;
} else {
  console.log("No iOS modal bugs reproduced.");
}
