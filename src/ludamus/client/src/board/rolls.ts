import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { PassKeeper, Roll } from "./bootstrap";

// The Worker keeps the latest 50 (workers/board/src/limits.ts).
const LOG_LENGTH = 50;

export type RollRefusal = "failed" | "too-fast";

export type Rolls = {
  // The roll everyone is looking at right now, until it settles.
  arrived: Roll | null;
  log: Roll[];
  receive: (message: unknown) => void;
  roll: (pool: number[]) => Promise<RollRefusal | null>;
  settle: () => void;
};

const isRollMessage = (message: unknown): message is { roll: Roll; type: "roll" } =>
  typeof message === "object" &&
  message !== null &&
  (message as { type?: unknown }).type === "roll" &&
  typeof (message as { roll?: { id?: unknown } }).roll?.id === "number";

export function useRolls(keeper: PassKeeper): Rolls {
  const [log, setLog] = useState<Roll[]>([]);
  const [arrived, setArrived] = useState<Roll | null>(null);
  const seen = useRef(new Set<number>());

  // The same roll comes back twice to its roller (as the answer and as the
  // room's message), and the log load can cross a message in flight.
  const add = useCallback((rolls: Roll[], announce: boolean) => {
    const fresh = rolls.filter(({ id }) => !seen.current.has(id));
    if (fresh.length === 0) return;
    for (const { id } of fresh) seen.current.add(id);
    setLog((current) => [...current, ...fresh].toSorted((a, b) => a.id - b.id).slice(-LOG_LENGTH));
    if (announce) setArrived(fresh.at(-1)!);
  }, []);

  const request = useCallback(
    async (path: string, init: RequestInit = {}) =>
      fetch(`${keeper.bootstrap.httpUrl}${path}`, {
        ...init,
        headers: { Authorization: `Bearer ${await keeper.pass()}`, ...init.headers },
      }),
    [keeper],
  );

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const response = await request("/rolls");
        if (cancelled) return;
        if (response.status === 403) return keeper.end("link-reset");
        if (!response.ok) throw new Error(`status ${response.status}`);
        add((await response.json()) as Roll[], false);
      } catch (error) {
        console.error("board: roll log did not load", error);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [add, keeper, request]);

  const roll = useCallback(
    async (pool: number[]): Promise<RollRefusal | null> => {
      try {
        const response = await request("/roll", {
          body: JSON.stringify({ dice: pool }),
          headers: { "Content-Type": "application/json" },
          method: "POST",
        });
        if (response.status === 429) return "too-fast";
        if (response.status === 403) {
          keeper.end("link-reset");
          return null;
        }
        if (!response.ok) throw new Error(`status ${response.status}`);
        add([(await response.json()) as Roll], true);
        return null;
      } catch (error) {
        console.error("board: roll failed", error);
        return "failed";
      }
    },
    [add, keeper, request],
  );

  const receive = useCallback(
    (message: unknown) => {
      if (isRollMessage(message)) add([message.roll], true);
    },
    [add],
  );
  const settle = useCallback(() => setArrived(null), []);

  return useMemo(
    () => ({ arrived, log, receive, roll, settle }),
    [arrived, log, receive, roll, settle],
  );
}
