import { baseUrl, createIosHarness, sessionName } from "./harness";
import { fetchReadyPage } from "./page";

// NOTE: this step exists to pay the XCUITest runner's `build-for-testing` --
// ~240s, once per job -- outside any spec's hook. It does NOT leave a runner
// standing for the specs: agent-device keys a runner to a session and stops it
// when that session closes, so each spec still launches its own (125-148s in
// the daemon log). The specs' first readiness pass absorbs that; this one only
// has to be wide enough for the build, which the workflow sets it to be.
//
// Warm also means Safari rendered a page served by this host -- the simulator
// reaching the host is a failure mode the workflow's own curl check cannot see.
// The label comes from the markup rather than a constant so no seed detail is
// pinned here.
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
  const label = firstTriggerLabel(html);
  await openUrl(eventUrl.toString(), { expectedLabels: [label], scope: label });
  console.log("Safari rendered the local page and the agent-device runner is built.");
} finally {
  await close();
}
