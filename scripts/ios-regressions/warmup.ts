import { baseUrl, createIosHarness } from "./harness";

// agent-device's runner attach -- not Safari -- is what times out
// (IOS_RUNNER_CONNECT_TIMEOUT), and the daemon spawn plus runner install costs
// 200s+ the first time. Whichever test file runs first used to absorb that
// inside a `beforeAll`, where it burns the hook budget and an attempt. Pay it
// here instead, in a step that is allowed to be slow and allowed to fail.
const session = process.env.SESSION ? `${process.env.SESSION}-warmup` : "zagrajmy-ios-warmup";
const eventPath = process.env.EVENT_PATH ?? "/event/autumn-open/";

const { openUrl, prepareDevice, takeSnapshot, assertPageReady } = await createIosHarness(session);

const eventUrl = new URL(eventPath, baseUrl);
await assertPageReady(eventUrl, "<html");
const udid = await prepareDevice();
await openUrl(eventUrl.toString(), udid);

// A snapshot round trip is the readiness signal: it only returns once the
// runner is attached and answering, which is exactly what we came to warm.
const snapshot = await takeSnapshot();
console.log(`Runner warm: ${snapshot.nodes.length} nodes.`);
