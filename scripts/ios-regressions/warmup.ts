import { baseUrl, createIosHarness, positiveMs, sessionName } from "./harness";
import { fetchReadyPage } from "./page";
import { pollUntil } from "./snapshot";

// Warm means the XCUITest runner is built, attached and answering and Safari
// has rendered a page served by this host -- the simulator reaching the host is
// a failure mode the workflow's own curl check cannot see. The label comes from
// the markup rather than a constant so no seed detail is pinned here.
const env = process.env;
const eventUrl = new URL(env.EVENT_PATH ?? "/event/autumn-open/", baseUrl);
const TRIGGER_LABELS = /aria-label="(Open details for [^"&]+)"/g;
const attachTimeoutMs = positiveMs("IOS_RUNNER_ATTACH_TIMEOUT_MS", 300000);

const { close, openUrl, prepareDevice, takeSnapshot } = createIosHarness(sessionName("warmup"));

const firstTriggerLabel = (html: string): string => {
  const label = [...html.matchAll(TRIGGER_LABELS)][0]?.[1];
  if (!label) throw new Error(`${eventUrl.toString()} rendered no session cards to warm up on.`);
  return label;
};

// SAFETY: the first runner command builds, launches and attaches the XCUITest
// runner, which measures 194-240s -- longer than one AGENT_DEVICE_RUNNER_-
// COMMAND_TIMEOUT_MS, so it reliably times out once before answering. Paying it
// here, against its own window, keeps a cold attach out of every readiness poll
// downstream; inside one it eats the whole budget and reports a page failure
// for what is really a runner that had not finished building.
const attachRunner = async (): Promise<void> => {
  console.log("Attaching the agent-device runner (first command builds it)...");
  const attached = await pollUntil(
    () =>
      takeSnapshot().then(
        () => true,
        (error: unknown) => {
          console.warn("Runner not answering yet; retrying.", error);
          return null;
        },
      ),
    { timeoutMs: attachTimeoutMs, intervalMs: 1000 },
  );
  if (!attached) {
    throw new Error(`The agent-device runner did not attach within ${attachTimeoutMs}ms.`);
  }
};

try {
  const html = await fetchReadyPage(eventUrl, "Open details for");
  await prepareDevice();
  await attachRunner();
  await openUrl(eventUrl.toString(), { expectedLabels: [firstTriggerLabel(html)] });
  console.log("Safari rendered the local page and the agent-device runner is attached.");
} finally {
  await close();
}
