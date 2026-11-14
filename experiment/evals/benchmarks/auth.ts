import { readFileSync } from "node:fs";
import path from "node:path";

import { Schema } from "effect";

const e2eDirectory = path.resolve(import.meta.dirname, "../../../tests/e2e");

const StoredCookieSchema = Schema.Struct({
  domain: Schema.String,
  name: Schema.String,
  value: Schema.String,
});

export type StoredCookie = typeof StoredCookieSchema.Type;

const AuthState = Schema.fromJsonString(
  Schema.Struct({ cookies: Schema.Array(StoredCookieSchema) })
);

const readAuthState = (authState: string) =>
  Schema.decodeUnknownSync(AuthState)(
    readFileSync(path.resolve(e2eDirectory, authState), "utf-8")
  );

export const cookieHeaderFor = (
  authState: string | undefined
): string | undefined => {
  if (authState === undefined) {
    return undefined;
  }

  const cookie = readAuthState(authState).cookies.find(
    (entry) => entry.name === "sessionid"
  );

  return cookie === undefined ? undefined : `${cookie.name}=${cookie.value}`;
};

export const storedCookies = (
  authState: string | undefined
): readonly StoredCookie[] => {
  if (authState === undefined) {
    return [];
  }

  return readAuthState(authState).cookies;
};
