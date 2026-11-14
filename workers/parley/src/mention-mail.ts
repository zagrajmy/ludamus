import { SignJWT } from "jose";

import { isLocal } from "./auth";

export const MENTIONS_AUDIENCE = "ludamus-mentions";

export const MAIL_AFTER_MS = 10 * 60_000;
export const MAIL_UNTIL_MS = 24 * 60 * 60_000;
export const RETRY_MS = 15 * 60_000;
export const MAX_LISTED = 50;

export type UnreadMention = {
  at: number;
  author: string;
  authorName: string;
  body: string;
  message: number;
  room: string;
};

export type MailOutcome = { kind: "failed" } | { kind: "handled" } | { at: number; kind: "later" };

type MailEnv = { PARLEY_MENTIONS_SECRET: string; ROOT_DOMAIN: string };

export const snippet = (body: string): string => [...body].slice(0, 280).join("");

export function appOrigin(rootDomain: string): string {
  const { hostname } = new URL(`http://${rootDomain}`);
  return `${isLocal(hostname) ? "http" : "https"}://${rootDomain}`;
}

export async function askToMail(
  env: MailEnv,
  { mentions, userId }: { mentions: UnreadMention[]; userId: string },
): Promise<MailOutcome> {
  const token = await new SignJWT({ mentions })
    .setProtectedHeader({ alg: "HS256", typ: "JWT" })
    .setIssuer("parley")
    .setAudience(MENTIONS_AUDIENCE)
    .setSubject(userId)
    .setIssuedAt()
    .setExpirationTime("5m")
    .sign(new TextEncoder().encode(env.PARLEY_MENTIONS_SECRET));
  let response: Response;
  try {
    response = await fetch(`${appOrigin(env.ROOT_DOMAIN)}/parley/mentions/`, {
      body: JSON.stringify({ token }),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    });
  } catch (error) {
    console.error("parley: mention mail request failed", error);
    return { kind: "failed" };
  }
  if (response.status === 204) return { kind: "handled" };
  if (response.status === 429) {
    const { retryAfter } = (await response.json()) as { retryAfter: number };
    return { at: Date.now() + retryAfter * 1_000, kind: "later" };
  }
  console.error("parley: mention mail refused", response.status);
  return { kind: "failed" };
}
