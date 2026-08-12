import type { CaptureSnapshotResult, SnapshotNode } from "agent-device";

import { afterAll, beforeAll, expect, test } from "bun:test";

import {
  baseUrl,
  centreOnScreen,
  createIosHarness,
  describeNode,
  hookTimeoutMs,
  pollUntil,
  sessionName,
} from "./harness";

const env = process.env;
const session = sessionName("modal");
const targetTitle = env.TARGET_SESSION_TITLE ?? "Przygoda w Mieście Neonów";
const targetTriggerLabel = env.TARGET_TRIGGER_LABEL ?? `Open details for ${targetTitle}`;
const eventPath = env.EVENT_PATH ?? "/event/autumn-open/";
const targetQueryParam = env.TARGET_QUERY_PARAM ?? "session=3";
const preOpenScrollSteps = 8;

const {
  client,
  deviceOptions,
  takeSnapshot,
  snapshotLabels,
  findNodeByLabel,
  viewportOf,
  close,
  wait,
  openUrl,
  prepareDevice,
  fetchReadyPage,
} = createIosHarness(session);

// `snapshotLabels` reports every label in the tree, including nodes scrolled
// out of view, so it cannot answer "is this on screen". The runner's `hittable`
// cannot either — the device run at 69a819a judged the open modal's own
// heading not hittable while the very next step tapped it; the field reads
// false inside Safari's web content. A rect centred in the viewport is the
// check that both survives the device and still fails for content parked
// below the fold of a modal that no longer sizes itself.
const showingLabels = async (): Promise<string[]> => {
  const snapshot = await takeSnapshot();
  return snapshot.nodes.flatMap((node) =>
    node.label && node.rect && isNodeInViewport(snapshot, node) ? [node.label] : [],
  );
};

// Polling, not sleeping: the modal animates in, and a single snapshot taken
// mid-animation reports content that is about to be there as missing.
const waitUntilShowing = async (texts: string[], timeoutMs: number): Promise<boolean> =>
  (await pollUntil(
    async () => {
      const labels = await showingLabels();
      return texts.every((text) => labels.some((label) => label.includes(text))) || null;
    },
    { timeoutMs, intervalMs: 400 },
  )) ?? false;

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

const isNodeInViewport = (snapshot: CaptureSnapshotResult, node: SnapshotNode): boolean =>
  Boolean(node.rect && centreOnScreen(node.rect, viewportOf(snapshot)));

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
    const viewportHeight = viewportOf(snapshot).height;
    const centerY = node?.rect ? node.rect.y + node.rect.height / 2 : viewportHeight;
    await client.interactions.scroll({
      ...deviceOptions,
      direction: centerY > viewportHeight - 120 ? "down" : "up",
      pixels: 450,
    });
    await wait(200);
  }

  throw new Error(`Could not bring ${targetTriggerLabel} into the viewport`);
};

const forcePreOpenScroll = async (): Promise<void> => {
  for (let step = 0; step < preOpenScrollSteps; step += 1) {
    await client.interactions.scroll({ ...deviceOptions, direction: "down", pixels: 450 });
    await wait(150);
  }
};

const waitForLabel = (label: string, timeoutMs: number): Promise<SnapshotNode | null> =>
  pollUntil(() => findNodeByLabel(label), { timeoutMs });

const eventUrl = new URL(eventPath, baseUrl);
const modalUrl = new URL(eventUrl);
for (const [key, value] of new URLSearchParams(targetQueryParam)) {
  modalUrl.searchParams.set(key, value);
}

const openViaScrolledPage = env.OPEN_VIA_SCROLLED_PAGE !== "0";

let contentIssue: string | null = null;
let closeIssue: string | null = null;
let scrollIssue: string | null = null;

beforeAll(async () => {
  await fetchReadyPage(eventUrl, targetTitle);
  const udid = await prepareDevice();

  const initialUrl = openViaScrolledPage ? eventUrl : modalUrl;
  console.log(`Opening Safari at ${initialUrl.toString()}...`);
  await openUrl(initialUrl.toString(), udid);
  await wait(3000);

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
  const contentInitiallyVisible = await waitUntilShowing(
    ["About this session", "Przygoda w stylu filmu"],
    5000,
  );
  if (!contentInitiallyVisible) {
    contentIssue =
      'Modal content headed by "About this session" / "Przygoda w stylu filmu" is not initially visible.';
  }

  console.log("Tapping Close...");
  const closeButton = await findNodeByLabel("Close");
  if (!closeButton) {
    throw new Error("Could not find visible target: Close");
  }
  await clickNodeCenter(closeButton);
  await wait(1000);

  // Closed means gone from the tree, not merely outside the visibility band —
  // the rect filter here would let a stuck-but-scrolled modal read as closed.
  if ((await snapshotLabels()).includes("Close")) {
    closeIssue = "The modal X / Close button did not close the modal.";
  }

  if (openViaScrolledPage && preOpenTriggerLabel && preOpenTriggerY !== null) {
    await wait(600);
    const settledSnapshot = await takeSnapshot();
    const settledTrigger = settledSnapshot.nodes.find(
      (node) => node.label === preOpenTriggerLabel && !isHiddenDialogLabel(node),
    );
    const settledY = settledTrigger?.rect?.y ?? null;
    if (settledY === null) {
      scrollIssue =
        `After closing, "${preOpenTriggerLabel}" was no longer in the viewport, ` +
        "so the page did not return to its pre-open scroll position.";
    } else if (Math.abs(settledY - preOpenTriggerY) > 200) {
      scrollIssue =
        `The page scroll jumped on close: "${preOpenTriggerLabel}" moved from ` +
        `y=${Math.round(preOpenTriggerY)} to y=${Math.round(settledY)} ` +
        "(>200px), so the scroll position was not preserved.";
    }
  }
}, hookTimeoutMs);

afterAll(close, 30_000);

test("modal content is visible when the session modal opens", () => {
  expect(contentIssue).toBeNull();
});

test("the Close button dismisses the session modal", () => {
  expect(closeIssue).toBeNull();
});

test("closing the modal preserves the page scroll position", () => {
  expect(scrollIssue).toBeNull();
});
