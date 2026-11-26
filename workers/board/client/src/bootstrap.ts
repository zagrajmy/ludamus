export type Person = { id: string; name: string; owner: boolean };

// What Django's pass endpoint answers (gates/web/django/whiteboard/views.py).
export type Bootstrap = {
  // The board's id: its room is /rooms/<board> on this origin.
  board: string;
  // "My boards" on the board's sphere, for a member; null for a guest.
  boardsUrl: string | null;
  pass: string;
  person: Person;
  sphere: { name: string; url: string };
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
  | { kind: "failed" | "gone" | "throttled" }
  | { kind: "name-invalid" | "name-required" };

// Django's pass endpoint for this board, on the app's own origin.
export type Door = { bootstrapUrl: string };

// NOTE: the request crosses origins with the session cookie, which the board
// host and the app share as one site. Django answers only this origin, and
// the JSON content type makes the browser ask it first (a CORS preflight).
export async function knock(door: Door, name?: string): Promise<Answer> {
  let response: Response;
  try {
    response = await fetch(door.bootstrapUrl, {
      body: JSON.stringify(name === undefined ? {} : { name }),
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      method: "POST",
    });
  } catch (error) {
    console.error("board: bootstrap unreachable", error);
    return { kind: "failed" };
  }
  if (response.status === 404) return { kind: "gone" };
  if (response.status === 429) return { kind: "throttled" };
  const body: unknown = await response.json().catch(() => null);
  const refusal = body as { error?: string } | null;
  if (
    response.status === 422 &&
    (refusal?.error === "name-required" || refusal?.error === "name-invalid")
  ) {
    return { kind: refusal.error };
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
    const origin = location.origin.replace(/^http/u, "ws");
    return `${origin}${this.room}/connect?pass=${encodeURIComponent(pass)}`;
  }

  // The board's rooms API, on the board's own origin.
  get room(): string {
    return `/rooms/${this.latest.board}`;
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
        if (answer.kind === "gone") this.end("gone");
        else if (answer.kind === "name-required") this.end("link-reset");
        throw new Error(`board: pass renewal ${answer.kind}`);
      })
      .finally(() => {
        this.pending = null;
      });
    return this.pending;
  }
}
