import { createIosHarness } from "./harness";

// agent-device's runner attach -- not Safari -- is what times out
// (IOS_RUNNER_CONNECT_TIMEOUT). The first runner-backed command triggers an
// `xcodebuild build-for-testing` plus runner launch and connect, which measures
// at 194-240s on a cold macOS runner. Whichever test file went first used to
// absorb that inside a `beforeAll`, where it burned the hook budget and an
// attempt. Pay it here instead, in a step allowed to be slow and allowed to
// fail. The runner is keyed by device and outlives the session that warmed it,
// so both test files inherit it.
const session = process.env.SESSION ? `${process.env.SESSION}-warmup` : "zagrajmy-ios-warmup";

const { client, prepareDevice, takeSnapshot } = await createIosHarness(session);

try {
  await prepareDevice();

  // A snapshot is the readiness signal: it is the round trip that installs and
  // attaches the runner, and it only returns once the runner answers.
  const snapshot = await takeSnapshot();
  console.log(`Runner warm: ${snapshot.nodes.length} nodes.`);
} finally {
  // Hand the device back even when warming failed, or the first test file
  // spends up to 15s evicting us from inside its own hook.
  await client.sessions.close({ session }).catch(() => undefined);
}
