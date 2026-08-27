import { baseUrl, createIosHarness, sessionName } from "./harness";

const { close, fetchReadyPage, openUrl, prepareDevice } = createIosHarness(sessionName("warmup"));
const eventUrl = new URL("/event/autumn-open/", baseUrl);

try {
  await fetchReadyPage(eventUrl, "Mega Strategy Lab");
  await prepareDevice();
  await openUrl(eventUrl.toString(), {
    expectedLabels: ["Open details for Mega Strategy Lab"],
  });
  console.log("Safari and the agent-device runner are ready.");
} finally {
  await close();
}
