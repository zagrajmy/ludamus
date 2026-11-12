import { createSign } from "node:crypto";
import { readFileSync } from "node:fs";
import type { IncomingMessage } from "node:http";
import { resolve } from "node:path";
import type { Plugin } from "vite";

// Stands in for Django's board bootstrap while the board is developed on its
// own: open /static/vite/src/board/dev/index.html on the Vite dev server.
// The query string picks the person (sub, name, owner, guest) and the board
// (board, link, lang). Serve-only, so it never reaches a production build.

const SIGNING_KEY = "../../../workers/parley/dev-signing-key.pem";
const PASS_LIFETIME_SECONDS = 300;
const MAX_NAME_LENGTH = 40;

const base64url = (value: Buffer | string) => Buffer.from(value).toString("base64url");

function signPass(key: string, claims: Record<string, unknown>): string {
  const issuedAt = Math.floor(Date.now() / 1000);
  const header = base64url(JSON.stringify({ alg: "RS256", typ: "JWT" }));
  const payload = base64url(
    JSON.stringify({
      ...claims,
      aud: "board",
      exp: issuedAt + PASS_LIFETIME_SECONDS,
      iat: issuedAt,
      iss: "ludamus",
    }),
  );
  const signature = createSign("RSA-SHA256").update(`${header}.${payload}`).sign(key);
  return `${header}.${payload}.${base64url(signature)}`;
}

async function bodyOf(request: IncomingMessage): Promise<{ name?: unknown }> {
  const chunks: Buffer[] = [];
  for await (const chunk of request) chunks.push(chunk as Buffer);
  try {
    return JSON.parse(Buffer.concat(chunks).toString() || "{}");
  } catch {
    return {};
  }
}

const POLISH: Record<string, string> = {
  addDie: "Dodaj %(die)s",
  addToPlaces: "Dodaj do miejsc",
  boardFull: "Tablica jest pełna. Dołączysz, gdy ktoś wyjdzie.",
  dice: "Kości",
  die: "k%(sides)s",
  guest: "gość",
  join: "Dołącz",
  myPlace: "Moje miejsce",
  noPlacesYet: "Nie ma jeszcze miejsc. Zaznacz kształt i dodaj go do miejsc.",
  noRollsYet: "Nikt jeszcze nie rzucał.",
  people: "Osoby",
  placeName: "Nazwa miejsca",
  places: "Miejsca",
  poolEmpty: "Dotknij kości, aby dodać je do puli.",
  removeDie: "Usuń %(die)s",
  removePlace: "Usuń z miejsc",
  roll: "Rzuć",
  rollAgain: "Rzuć jeszcze raz",
  rolledBy: "Rzuca %(name)s",
  rollLog: "Historia rzutów",
  total: "Suma",
  you: "ty",
  yourName: "Twoje imię",
};

export function boardHarness({ worker }: { worker: string }): Plugin {
  const guestNames = new Map<string, string>();
  return {
    apply: "serve",
    configureServer(server) {
      const key = readFileSync(resolve(server.config.root, SIGNING_KEY), "utf8");
      server.middlewares.use("/dev-board/bootstrap/", async (request, response) => {
        const query = new URL(request.url ?? "/", "http://harness").searchParams;
        const board = query.get("board") ?? "dev";
        const sub = query.get("sub") ?? "u:1";
        const guest = sub.startsWith("g:");
        const { name: typed } = await bodyOf(request);
        if (typeof typed === "string" && typed.trim().length > 0) {
          guestNames.set(sub, typed.trim().slice(0, MAX_NAME_LENGTH));
        }
        const name = guest ? guestNames.get(sub) : (query.get("name") ?? "Ania");
        response.setHeader("Content-Type", "application/json");
        if (query.get("gone") === "1") {
          response.statusCode = 404;
          response.end("{}");
          return;
        }
        if (name === undefined) {
          response.statusCode = 422;
          response.end(JSON.stringify({ error: "name-required" }));
          return;
        }
        const owner = query.get("owner") === "1";
        const link = Number(query.get("link") ?? "0");
        response.end(
          JSON.stringify({
            copy: query.get("lang") === "pl" ? POLISH : {},
            httpUrl: `${worker.replace(/^ws/u, "http")}/rooms/${board}`,
            pass: signPass(key, { board, link, name, owner, sub }),
            person: { id: sub, name, owner },
            socketUrl: `${worker.replace(/^http/u, "ws")}/rooms/${board}`,
            title: "Harness board",
          }),
        );
      });
    },
    name: "board-harness",
  };
}
