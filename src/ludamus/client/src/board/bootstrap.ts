import type { Copy } from "./copy";

export type Person = { id: string; name: string; owner: boolean };

export type Bootstrap = {
  copy: Partial<Copy>;
  httpUrl: string;
  pass: string;
  person: Person;
  socketUrl: string;
  title: string;
};

// The roll as the Worker records it (workers/board/src/dice.ts).
export type Roll = {
  at: number;
  dice: { sides: number; value: number }[];
  id: number;
  name: string;
  sub: string;
};

export type Answer =
  | { bootstrap: Bootstrap; kind: "ready" }
  | { copy: Partial<Copy>; kind: "name-required" }
  | { kind: "failed" }
  | { kind: "gone" };

export type Door = { bootstrapUrl: string; csrfToken: string };

export async function knock(door: Door, name?: string): Promise<Answer> {
  let response: Response;
  try {
    response = await fetch(door.bootstrapUrl, {
      body: JSON.stringify(name === undefined ? {} : { name }),
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": door.csrfToken },
      method: "POST",
    });
  } catch (error) {
    console.error("board: bootstrap unreachable", error);
    return { kind: "failed" };
  }
  if (response.status === 404) return { kind: "gone" };
  const body: unknown = await response.json().catch(() => null);
  if (response.status === 422 && (body as { error?: string } | null)?.error === "name-required") {
    return { copy: (body as { copy?: Partial<Copy> }).copy ?? {}, kind: "name-required" };
  }
  if (!response.ok || body === null) {
    console.error("board: bootstrap refused", response.status);
    return { kind: "failed" };
  }
  return { bootstrap: body as Bootstrap, kind: "ready" };
}

// NOTE: a pass lives five minutes. One older than this is fetched again
// before use, so a request never leaves with a pass about to expire.
const PASS_REUSE_MS = 4 * 60_000;

export type Ending = "gone" | "link-reset";

// Keeps a usable pass for one board: the socket asks for one on every
// (re)connect, and each roll request carries one.
export class PassKeeper {
  private latest: Bootstrap;
  private issuedAt = Date.now();
  private pending: Promise<Bootstrap> | null = null;

  constructor(
    private readonly door: Door,
    first: Bootstrap,
    private readonly onEnding: (ending: Ending) => void,
  ) {
    this.latest = first;
  }

  get bootstrap(): Bootstrap {
    return this.latest;
  }

  async pass(): Promise<string> {
    if (Date.now() - this.issuedAt < PASS_REUSE_MS) return this.latest.pass;
    const renewed = await this.renew();
    return renewed.pass;
  }

  async socketUri(): Promise<string> {
    const pass = await this.pass();
    return `${this.latest.socketUrl}/connect?pass=${encodeURIComponent(pass)}`;
  }

  end(ending: Ending): void {
    this.onEnding(ending);
  }

  private renew(): Promise<Bootstrap> {
    this.pending ??= knock(this.door)
      .then((answer) => {
        if (answer.kind === "ready") {
          this.latest = answer.bootstrap;
          this.issuedAt = Date.now();
          return answer.bootstrap;
        }
        // NOTE: a person Django no longer lets in (board deleted, or a guest
        // put out by a link reset) gets 404 or a name request back.
        if (answer.kind !== "failed") this.end(answer.kind === "gone" ? "gone" : "link-reset");
        throw new Error(`board: pass renewal ${answer.kind}`);
      })
      .finally(() => {
        this.pending = null;
      });
    return this.pending;
  }
}
