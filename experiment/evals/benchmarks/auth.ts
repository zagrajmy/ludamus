import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const e2eDirectory = resolve(import.meta.dirname, "../../../tests/e2e");

export type StoredCookie = Readonly<{
  name: string;
  value: string;
  domain: string;
}>;

export const cookieHeaderFor = (
  authState: string | undefined
): string | undefined => {
  if (authState === undefined) {
    return undefined;
  }

  const state: { cookies: readonly StoredCookie[] } = JSON.parse(
    readFileSync(resolve(e2eDirectory, authState), "utf-8")
  );

  const cookie = state.cookies.find((entry) => entry.name === "sessionid");

  return cookie === undefined ? undefined : `${cookie.name}=${cookie.value}`;
};

export const storedCookies = (
  authState: string | undefined
): readonly StoredCookie[] => {
  if (authState === undefined) {
    return [];
  }

  const state: { cookies: readonly StoredCookie[] } = JSON.parse(
    readFileSync(resolve(e2eDirectory, authState), "utf-8")
  );

  return state.cookies;
};
