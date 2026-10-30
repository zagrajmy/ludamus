import { describe, expect, it } from "@effect/vitest";
import { Effect, Exit } from "effect";

import { decodeSessionData, sessionAuthHash } from "../src/django-signing.js";

const SECRET = "e2e-secret-key";
const SESSION_DATA =
  ".eJxVjDsOwjAQBe_iGln-m1DScwZrd73BAWRLcVIh7k4ipYD2zcx7iwTrUtLaeU5TFhfhxel3Q6An1x3kB9R7k9TqMk8od0UetMtby_y6Hu7fQYFetnpwxkYE9hFNJh890mDQKotZOxUxANugrCNGHoOHbNFsig4jRc1nFp8v7Po4hg:1xMrrw:CYITmx39zeZZuGiLaS9djgpS49hnRyU1DGiCjcWBKXo";

describe("django session signing", () => {
  it.effect("decodes a compressed, signed session written by Django", () =>
    Effect.gen(function* () {
      const payload = yield* decodeSessionData(SESSION_DATA, SECRET);

      expect(payload._auth_user_id).toBe("5");
      expect(payload._auth_user_backend).toBe(
        "django.contrib.auth.backends.ModelBackend"
      );
    })
  );

  it.effect("rejects a session signed with another secret", () =>
    Effect.gen(function* () {
      const exit = yield* Effect.exit(decodeSessionData(SESSION_DATA, "other"));

      expect(Exit.isFailure(exit)).toBe(true);
    })
  );

  it.effect("rejects a tampered payload", () =>
    Effect.gen(function* () {
      const tampered = `.eJy${SESSION_DATA.slice(4)}`;
      const exit = yield* Effect.exit(decodeSessionData(tampered, SECRET));

      expect(Exit.isFailure(exit)).toBe(true);
    })
  );

  it("matches Django's get_session_auth_hash for an unusable password", () => {
    expect(sessionAuthHash("!l1UDTUd4MJJqbQOYN4GayIsZgFwf5JFFFxEKlCs9", SECRET)).toBe(
      "94237bae57b2dc575bc92b303bd1407b6ae36034cebef65ad3b2bc916fc71e8e"
    );
  });
});
