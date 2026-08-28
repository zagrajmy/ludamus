import { baseUrl, createIosHarness, sessionName } from "./harness";
import { fetchReadyPage } from "./page";

// Warm means the XCUITest runner is built, attached and answering and Safari
// has rendered a page served by this host -- the simulator reaching the host is
// a failure mode the workflow's own curl check cannot see. The label comes from
// the markup rather than a constant so no seed detail is pinned here.
const env = process.env;
const eventUrl = new URL(env.EVENT_PATH ?? "/event/autumn-open/", baseUrl);
const TRIGGER_LABELS = /aria-label="(Open details for [^"&]+)"/g;

const { close, openUrl, prepareDevice } = createIosHarness(sessionName("warmup"));

const firstTriggerLabel = (html: string): string => {
  const label = [...html.matchAll(TRIGGER_LABELS)][0]?.[1];
  if (!label) throw new Error(`${eventUrl.toString()} rendered no session cards to warm up on.`);
  return label;
};

try {
  const html = await fetchReadyPage(eventUrl, "Open details for");
  await prepareDevice();
  await openUrl(eventUrl.toString(), { expectedLabels: [firstTriggerLabel(html)] });
  console.log("Safari rendered the local page and the agent-device runner is attached.");
} finally {
  await close();
}
