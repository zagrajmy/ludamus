import { NodeHttpServer } from "@effect/platform-node";
import { describe, expect, it } from "@effect/vitest";
import { defineContract, implement } from "@zagrajmy/capability";
import { CrossSiteRequest, UnknownHost } from "@zagrajmy/capability/refusal";
import { Sphere, SphereId } from "@zagrajmy/core";
import { UserRow } from "@zagrajmy/database";
import { Effect, Layer, Option, Schema } from "effect";
import { HttpRouter } from "effect/http";

import { RequestContext } from "../src/request-context.js";
import { httpApiFor } from "../src/surfaces.js";

const HOST = "localhost:8000";

const sphere = Sphere.make({
  domain: HOST,
  id: SphereId.make(1),
  name: "Root",
});

const viewer = UserRow.make({
  email: "ola@example.com",
  id: 7,
  isActive: 1,
  isSuperuser: 0,
  name: "Ola",
  password: "",
  slug: "ola",
  username: "ola",
});

const enrollContract = defineContract("enroll", {
  description: "A write that needs a signed-in user",
  failure: Schema.Never,
  input: Schema.Struct({}),
  output: Schema.Struct({ ok: Schema.Boolean }),
});

const enroll = implement(enrollContract, () => Effect.succeed({ ok: true }));

const fakeContext = RequestContext.of({
  clientIp: () => Option.none(),
  services: () => Effect.die("unused by the HTTP hooks"),
  sphere: (host) =>
    host === HOST
      ? Effect.succeed(sphere)
      : Effect.fail(new UnknownHost({ host: host ?? "" })),
  user: (headers) =>
    Effect.succeed(
      headers.cookie === undefined ? Option.none() : Option.some(viewer)
    ),
  viewer: () => Effect.succeed(Option.none()),
});

const call = (headers: Readonly<Record<string, string>>) =>
  Effect.gen(function* callEnroll() {
    const { dispose, handler } = HttpRouter.toWebHandler(
      httpApiFor([enroll], fakeContext).routes.pipe(
        Layer.provide(NodeHttpServer.layerHttpServices)
      ),
      { disableLogger: true }
    );

    yield* Effect.addFinalizer(() => Effect.promise(dispose));

    const response = yield* Effect.promise(
      // oxlint-disable-next-line typescript/promise-function-async -- HttpRouter.toWebHandler exposes a Promise API at this in-memory boundary.
      () =>
        handler(
          new Request(`http://${HOST}/api/enroll`, {
            body: "{}",
            headers: {
              "content-type": "application/json",
              host: HOST,
              ...headers,
            },
            method: "POST",
          })
        )
    );

    // oxlint-disable-next-line typescript/promise-function-async -- Response.json is the Web boundary.
    const body = yield* Effect.promise(() => response.json());

    return { body, status: response.status };
  });

describe("HTTP API surface", () => {
  it.effect("runs a same-origin write for a signed-in viewer", () =>
    Effect.gen(function* admitted() {
      expect(
        yield* call({ cookie: "sessionid=x", origin: `http://${HOST}` })
      ).toEqual({
        body: { ok: true },
        status: 200,
      });
    })
  );

  it.effect("answers 403 to a cross-site write, signed in or not", () =>
    Effect.gen(function* crossSite() {
      const answer = yield* call({
        cookie: "sessionid=x",
        origin: "https://evil.example",
      });

      const refusal = yield* Schema.decodeUnknownEffect(CrossSiteRequest)(
        answer.body
      );

      expect(answer.status).toBe(403);
      expect(refusal).toEqual(
        new CrossSiteRequest({ capabilityName: "enroll" })
      );
    })
  );

  it.effect("answers 401 to a write without a signed-in viewer", () =>
    Effect.gen(function* signedOut() {
      expect((yield* call({ "sec-fetch-site": "same-origin" })).status).toBe(
        401
      );
    })
  );

  it.effect("answers 404 for a host no sphere serves", () =>
    Effect.gen(function* unknownHost() {
      expect(
        (yield* call({ cookie: "sessionid=x", host: "nowhere.localhost:8000" }))
          .status
      ).toBe(404);
    })
  );
});
