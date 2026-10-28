import { afterAll, beforeAll, expect, test } from "bun:test";
import { mkdir } from "node:fs/promises";
import path from "node:path";

import { baseUrl, hookTimeoutMs } from "./harness";
import { pollUntil } from "./snapshot";

// NOTE: the Markdown editor paints highlighted text in a <pre> laid over its
// <textarea>, whose own glyphs are transparent. iOS WebKit has been known to
// inset a textarea's text a few points inside its padding; the textarea would
// then wrap earlier than the painting and the caret would drift off the text.
// agent-device reads only the accessibility tree, which shows neither layer's
// line boxes, so this spec measures layout through Safari's WebDriver instead.

const env = process.env;
const driverPort = Number(env.SAFARIDRIVER_PORT ?? 4445);
const driverUrl = `http://localhost:${driverPort}`;
const formUrl = new URL("/encounters/create/", baseUrl);
const shotsDir = `${env.RUNNER_TEMP ?? "/tmp"}/ios-shots`;
const authState = path.join(import.meta.dir, "../../tests/e2e/.auth-state.json");

const FIELD = "textarea[data-markdown-editor=ready]";

const DESCRIPTION = [
  "Bring your own **dice**, pencils and a sense of adventure, because the night will be long and the dungeon is deep and full of traps.",
  "We start at seven sharp; latecomers can join after the first encounter wraps up, around half past eight or so.",
  "- snacks welcome\n- [rules](https://example.com/rules) are on the table",
].join("\n\n");

// NOTE: the inset reported for iOS WebKit is 3pt a side; the control adds just
// that to prove the sweep would notice it.
const INSET_PX = 3;
const SWEEP_PX = 80;

type Sweep = { mismatches: number[][]; lines: number; painted: string; value: string };

// NOTE: narrows the editor a pixel at a time and records every width where the
// textarea's own text needs a different height than the painting. The layers
// wrap differently only if their text boxes differ in width, and across this
// many widths some word lands within a few pixels of the edge.
const SWEEP_SCRIPT = `
  const [sweepPx, insetPx] = arguments;
  const textarea = document.querySelector("${FIELD}");
  const pre = textarea.nextElementSibling;
  const root = textarea.parentElement;
  const start = Math.round(root.getBoundingClientRect().width);
  if (insetPx) {
    const style = getComputedStyle(textarea);
    textarea.style.paddingLeft = parseFloat(style.paddingLeft) + insetPx + "px";
    textarea.style.paddingRight = parseFloat(style.paddingRight) + insetPx + "px";
  }
  const mismatches = [];
  for (let width = start; width > start - sweepPx; width -= 1) {
    root.style.width = width + "px";
    textarea.style.height = "0";
    const typed = textarea.scrollHeight;
    textarea.style.height = "100%";
    if (typed !== pre.clientHeight) mismatches.push([width, typed, pre.clientHeight]);
  }
  root.style.width = "";
  textarea.style.paddingLeft = "";
  textarea.style.paddingRight = "";
  const lines = Math.round(
    (pre.clientHeight - parseFloat(getComputedStyle(pre).paddingTop) * 2) /
      parseFloat(getComputedStyle(pre).lineHeight),
  );
  return { mismatches, lines, painted: pre.innerText, value: textarea.value };
`;

type WebDriverValue = Record<string, unknown> | string | null;

const call = async (method: string, route: string, body?: unknown): Promise<WebDriverValue> => {
  const response = await fetch(`${driverUrl}${route}`, {
    method,
    headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(180_000),
  });
  const payload = (await response.json()) as { value: WebDriverValue };
  if (!response.ok) {
    throw new Error(`WebDriver ${method} ${route} failed: ${JSON.stringify(payload.value)}`);
  }
  return payload.value;
};

let driver: ReturnType<typeof Bun.spawn> | null = null;
let sessionPath: string | null = null;
let measured: Sweep | null = null;
let control: Sweep | null = null;

const run = async (script: string, args: unknown[] = []): Promise<unknown> =>
  call("POST", `${sessionPath}/execute/sync`, { script, args });

beforeAll(async () => {
  driver = Bun.spawn(["safaridriver", "-p", String(driverPort)], { stdout: "inherit" });
  const ready = await pollUntil(
    async () => {
      try {
        const status = await call("GET", "/status");
        return typeof status === "object" && status?.ready ? true : null;
      } catch {
        return null;
      }
    },
    { timeoutMs: 15_000, intervalMs: 250 },
  );
  if (!ready) throw new Error(`safaridriver did not answer on ${driverUrl}.`);

  const session = await call("POST", "/session", {
    capabilities: {
      alwaysMatch: {
        platformName: "iOS",
        browserName: "Safari",
        "safari:useSimulator": true,
        ...(env.UDID ? { "safari:deviceUDID": env.UDID } : {}),
      },
    },
  });
  if (typeof session !== "object" || typeof session?.sessionId !== "string") {
    throw new Error(`safaridriver opened no session: ${JSON.stringify(session)}`);
  }
  sessionPath = `/session/${session.sessionId}`;

  const { cookies } = (await Bun.file(authState).json()) as {
    cookies: { name: string; value: string }[];
  };
  await call("POST", `${sessionPath}/url`, { url: new URL("/", baseUrl).toString() });
  for (const { name, value } of cookies) {
    await call("POST", `${sessionPath}/cookie`, { cookie: { name, value, path: "/" } });
  }
  await call("POST", `${sessionPath}/url`, { url: formUrl.toString() });
  const enhanced = await pollUntil(
    async () => ((await run(`return Boolean(document.querySelector("${FIELD}"));`)) ? true : null),
    { timeoutMs: 15_000, intervalMs: 250 },
  );
  if (!enhanced) throw new Error(`No Markdown editor came up at ${formUrl.toString()}.`);

  // NOTE: Safari's WebDriver on iOS drops key actions aimed at a textarea, so
  // the text goes in through the editing command a keyboard uses, one line at
  // a time, firing the same input events.
  await run(
    `const textarea = document.querySelector("${FIELD}");
     textarea.focus();
     for (const part of arguments[0]) document.execCommand("insertText", false, part);`,
    [DESCRIPTION.split(/(?<=\n)/)],
  );

  measured = (await run(SWEEP_SCRIPT, [SWEEP_PX, 0])) as Sweep;
  control = (await run(SWEEP_SCRIPT, [SWEEP_PX, INSET_PX])) as Sweep;
  console.log(
    `Sweep: ${JSON.stringify(measured.mismatches)}; control: ${control.mismatches.length} mismatches`,
  );

  const field = (await call("POST", `${sessionPath}/element`, {
    using: "css selector",
    value: FIELD,
  })) as Record<string, string>;
  const [fieldId] = Object.values(field);
  const shot = await call("GET", `${sessionPath}/element/${fieldId}/screenshot`);
  if (typeof shot === "string") {
    await mkdir(shotsDir, { recursive: true });
    await Bun.write(`${shotsDir}/markdown-overlay.png`, Buffer.from(shot, "base64"));
  }
}, hookTimeoutMs);

afterAll(async () => {
  try {
    if (sessionPath) await call("DELETE", sessionPath);
  } finally {
    driver?.kill();
  }
}, 30_000);

test("the painting holds exactly the typed text", () => {
  expect(measured?.value).toBe(DESCRIPTION);
  expect(measured?.painted.trimEnd()).toBe(DESCRIPTION);
});

test("the description wraps over several lines", () => {
  expect(measured?.lines).toBeGreaterThan(8);
});

test("the sweep notices a textarea inset by a few points", () => {
  expect(control?.mismatches.length).toBeGreaterThan(0);
});

test("the textarea wraps its text exactly where the painting does", () => {
  expect(measured?.mismatches).toEqual([]);
});
