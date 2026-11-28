import { Agent, request } from "node:http";
import type { OutgoingHttpHeaders } from "node:http";
import { performance } from "node:perf_hooks";

import { Effect } from "effect";
import { constVoid } from "effect/Function";

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

const requestHeaders = (url: URL, cookie: string | undefined) => {
  const headers: OutgoingHttpHeaders = {
    accept: "text/html,application/xhtml+xml",
    "accept-language": "en-US,en;q=0.9",
    host: url.host,
  };

  if (cookie !== undefined) {
    headers.cookie = cookie;
  }

  return headers;
};

const sample = (target: {
  readonly agent: Agent;
  readonly url: URL;
  readonly cookie: string | undefined;
}) =>
  Effect.callback<Sample, Error>((resume) => {
    const { agent, url, cookie } = target;
    const started = performance.now();
    let firstByte = started;
    let bytes = 0;

    const outgoing = request(
      {
        agent,
        headers: requestHeaders(url, cookie),
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
          resume(
            Effect.succeed({
              bytes,
              status: incoming.statusCode ?? 0,
              totalMs: performance.now() - started,
              ttfbMs: firstByte - started,
            })
          );
        });
        incoming.on("error", (failure) => {
          resume(Effect.fail(failure));
        });
      }
    );

    outgoing.on("error", (failure) => {
      resume(Effect.fail(failure));
    });
    outgoing.end();
  });

export const measureLoad = async (
  options: LoadOptions
): Promise<LoadResult> => {
  const url = new URL(options.url);
  const agent = new Agent({ keepAlive: true, maxSockets: options.connections });

  const target = { agent, cookie: options.cookie, url };

  await Effect.runPromise(
    Effect.forEach(
      Array.from({ length: options.warmupRequests }),
      () => sample(target),
      { discard: true }
    )
  );

  const ttfb: number[] = [];
  const total: number[] = [];
  const statuses: Record<string, number> = {};
  let bytes = 0;
  let errors = 0;
  const deadline = performance.now() + options.durationMs;

  const record = (taken: Sample) => {
    ttfb.push(taken.ttfbMs);
    total.push(taken.totalMs);
    bytes += taken.bytes;
    statuses[String(taken.status)] = (statuses[String(taken.status)] ?? 0) + 1;
  };

  const worker = Effect.whileLoop({
    body: () =>
      sample(target).pipe(
        Effect.match({
          onFailure: () => {
            errors += 1;
          },
          onSuccess: record,
        })
      ),
    step: constVoid,
    while: () => performance.now() < deadline,
  });

  const started = performance.now();
  await Effect.runPromise(
    Effect.all(
      Array.from({ length: options.connections }, () => worker),
      { concurrency: "unbounded", discard: true }
    )
  );
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
