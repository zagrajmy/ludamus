import { Buffer } from "node:buffer";
import { createHash, createHmac, timingSafeEqual } from "node:crypto";
import { inflateSync } from "node:zlib";

import { Data, Effect, Schema } from "effect";

export class InvalidSession extends Data.TaggedError("InvalidSession")<{
  readonly reason: string;
}> {}

const SESSION_KEY_SALT = "django.contrib.sessions.SessionStore";

const SessionPayload = Schema.Struct({
  _auth_user_backend: Schema.optional(Schema.String),
  _auth_user_hash: Schema.optional(Schema.String),
  _auth_user_id: Schema.optional(Schema.String),
});
export type SessionPayload = typeof SessionPayload.Type;

const base64UrlDecode = (value: string) =>
  Buffer.from(value, "base64url");

const base64UrlEncode = (value: Buffer) =>
  value.toString("base64url");

const saltedHmac = (keySalt: string, value: string, secret: string) => {
  const key = createHash("sha256").update(`${keySalt}${secret}`).digest();

  return createHmac("sha256", key).update(value).digest();
};

const signature = (salt: string, value: string, secret: string) =>
  base64UrlEncode(saltedHmac(`${salt}signer`, value, secret));

const constantTimeEqual = (left: string, right: string) => {
  const a = Buffer.from(left);
  const b = Buffer.from(right);

  return a.length === b.length && timingSafeEqual(a, b);
};

export const sessionAuthHash = (password: string, secret: string) =>
  saltedHmac(
    "django.contrib.auth.models.AbstractBaseUser.get_session_auth_hash",
    password,
    secret
  ).toString("hex");

export const decodeSessionData = (sessionData: string, secret: string) =>
  Effect.gen(function* decodeDjangoSession() {
    const lastColon = sessionData.lastIndexOf(":");

    if (lastColon < 0) {
      return yield* new InvalidSession({ reason: "no signature" });
    }

    const signedValue = sessionData.slice(0, lastColon);
    const providedSignature = sessionData.slice(lastColon + 1);

    if (
      !constantTimeEqual(
        signature(SESSION_KEY_SALT, signedValue, secret),
        providedSignature
      )
    ) {
      return yield* new InvalidSession({ reason: "bad signature" });
    }

    const timestampColon = signedValue.lastIndexOf(":");

    if (timestampColon < 0) {
      return yield* new InvalidSession({ reason: "no timestamp" });
    }

    const encoded = signedValue.slice(0, timestampColon);
    const compressed = encoded.startsWith(".");
    const raw = base64UrlDecode(compressed ? encoded.slice(1) : encoded);

    const json = yield* Effect.try({
      catch: () => new InvalidSession({ reason: "undecodable payload" }),
      try: () => (compressed ? inflateSync(raw) : raw).toString("utf8"),
    });

    return yield* Schema.decodeUnknownEffect(
      Schema.fromJsonString(SessionPayload)
    )(json).pipe(
      Effect.mapError(() => new InvalidSession({ reason: "unexpected payload" }))
    );
  });
