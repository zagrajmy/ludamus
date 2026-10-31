import { Agent, request } from "node:http";
import { performance } from "node:perf_hooks";

import { summarize } from "./stats.ts";
import type { Summary } from "./stats.ts";

export type LoadOptions = Readonly<{
  url: string;
  cookie?: string | undefined;
  connections: number;
  durationMs: number;
  warmupRequests: number;
}>;

export type LoadResult = Readonly<{
  url: string;
  connections: number;
  durationMs: number;
  requests: number;
  errors: number;
  statuses: Record<string, number>;
  requestsPerSecond: number;
  bytesPerResponse: number;
  ttfbMs: Summary;
  totalMs: Summary;
}>;

type Sample = Readonly<{
  bytes: number;
  status: number;
  totalMs: number;
  ttfbMs: number;
}>;

const loopbackFor = (hostname: string) =>
  hostname === "localhost" || hostname.endsWith(".localhost")
    ? "127.0.0.1"
    : hostname;

const once = async (agent: Agent, url: URL, cookie: string | undefined) =>
  new Promise<Sample>((resolvePromise, rejectPromise) => {
    const started = performance.now();
    let firstByte = started;
    let bytes = 0;

    const outgoing = request(
      {
        agent,
        headers: {
          accept: "text/html,application/xhtml+xml",
          "accept-language": "en-US,en;q=0.9",
          host: url.host,
          ...(cookie === undefined ? {} : { cookie }),
        },
        host: loopbackFor(url.hostname),
        method: "GET",
        path: `${url.pathname}${url.search}`,
        port: url.port === "" ? 80 : Number(url.port),
      },
      (incoming) => {
        firstByte = performance.now();
        incoming.on("data", (chunk: Buffer) => {
          bytes += chunk.length;
        });
        incoming.on("end", () => {
          resolvePromise({
            bytes,
            status: incoming.statusCode ?? 0,
            totalMs: performance.now() - started,
            ttfbMs: firstByte - started,
          });
        });
        incoming.on("error", rejectPromise);
      }
    );

    outgoing.on("error", rejectPromise);
    outgoing.end();
  });

export const measureLoad = async (
  options: LoadOptions
): Promise<LoadResult> => {
  const url = new URL(options.url);
  const agent = new Agent({ keepAlive: true, maxSockets: options.connections });

  for (let index = 0; index < options.warmupRequests; index += 1) {
    await once(agent, url, options.cookie);
  }

  const ttfb: number[] = [];
  const total: number[] = [];
  const statuses: Record<string, number> = {};
  let bytes = 0;
  let errors = 0;
  const deadline = performance.now() + options.durationMs;

  const worker = async () => {
    while (performance.now() < deadline) {
      try {
        const sample = await once(agent, url, options.cookie);
        ttfb.push(sample.ttfbMs);
        total.push(sample.totalMs);
        bytes += sample.bytes;
        statuses[String(sample.status)] =
          (statuses[String(sample.status)] ?? 0) + 1;
      } catch {
        errors += 1;
      }
    }
  };

  const started = performance.now();
  await Promise.all(Array.from({ length: options.connections }, worker));
  const elapsedMs = performance.now() - started;
  agent.destroy();

  return {
    bytesPerResponse: total.length === 0 ? 0 : Math.round(bytes / total.length),
    connections: options.connections,
    durationMs: Math.round(elapsedMs),
    errors,
    requests: total.length,
    requestsPerSecond: total.length / (elapsedMs / 1000),
    statuses,
    totalMs: summarize(total),
    ttfbMs: summarize(ttfb),
    url: options.url,
  };
};
