import { baseUrl, createIosHarness, sessionName } from "./harness";

// Warm means the XCUITest runner is built, attached and answering and Safari is
// frontmost -- not that any page is seeded. The workflow gates the server
// before this step and each spec fetches its own page, so opening the site root
// keeps warming independent of the fixtures a spec happens to want.
const { close, openUrl, prepareDevice } = createIosHarness(sessionName("warmup"));

try {
  await prepareDevice();
  await openUrl(baseUrl);
  console.log("Safari is up and the agent-device runner is attached.");
} finally {
  await close();
}
