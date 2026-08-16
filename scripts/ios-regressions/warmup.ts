import { createIosHarness, sessionName } from "./harness";

const { close, prepareDevice, takeSnapshot } = createIosHarness(sessionName("warmup"));

try {
  await prepareDevice();

  // A snapshot is the readiness signal: it is the round trip that builds,
  // launches and attaches the XCUITest runner, and it only returns once the
  // runner answers. The runner is keyed by device and outlives this session,
  // so both test files inherit it.
  const snapshot = await takeSnapshot();
  console.log(`Runner warm: ${snapshot.nodes.length} nodes.`);
} finally {
  // Hand the device back even when warming failed, or the first test file
  // spends up to 15s evicting us from inside its own hook.
  await close();
}
