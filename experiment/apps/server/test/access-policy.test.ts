import { describe, expect, it } from "@effect/vitest";
import { defineContract, implement } from "@zagrajmy/capability";
import { CrossSiteRequest, SignInRequired } from "@zagrajmy/capability/refusal";
import { Effect, Option, Schema } from "effect";
import * as Headers from "effect/http/Headers";
import * as HttpServerRequest from "effect/http/HttpServerRequest";

import {
  admit,
  requirementOf,
  strictestRequirement,
} from "../src/access-policy.js";
import { contractForRequest } from "../src/http-hooks.js";
import { isSameOrigin } from "../src/request-context.js";

const contract = (
  name: string,
  annotations: { readonly anonymousSafe?: boolean; readonly readOnly?: boolean }
) =>
  defineContract(name, {
    annotations,
    description: name,
    failure: Schema.Never,
    input: Schema.Struct({}),
    output: Schema.Void,
  });

const read = contract("readEvents", { readOnly: true });

const write = contract("enroll", {});

const anonymousWrite = contract("proposeAnonymously", { anonymousSafe: true });

const sameSiteSignedIn = { sameOrigin: true, signedIn: true };

const outcome = (effect: ReturnType<typeof admit>) =>
  effect.pipe(
    Effect.match({
      onFailure: (refusal) => refusal._tag,
      onSuccess: () => "admitted",
    })
  );

describe("admit", () => {
  it.effect("lets a read through from any site and any viewer", () =>
    Effect.gen(function* reads() {
      expect(
        yield* outcome(
          admit(requirementOf(read), { sameOrigin: false, signedIn: false })
        )
      ).toBe("admitted");
    })
  );

  it.effect("refuses a cross-site write before looking at the viewer", () =>
    Effect.gen(function* crossSite() {
      const refusal = yield* admit(requirementOf(write), {
        sameOrigin: false,
        signedIn: true,
      }).pipe(Effect.flip);

      expect(refusal).toEqual(
        new CrossSiteRequest({ capabilityName: "enroll" })
      );
    })
  );

  it.effect("asks a signed-out viewer to sign in for a write", () =>
    Effect.gen(function* signedOut() {
      const refusal = yield* admit(requirementOf(write), {
        sameOrigin: true,
        signedIn: false,
      }).pipe(Effect.flip);

      expect(refusal).toEqual(new SignInRequired({ capabilityName: "enroll" }));
      expect(
        yield* outcome(admit(requirementOf(write), sameSiteSignedIn))
      ).toBe("admitted");
    })
  );

  it.effect(
    "admits an anonymous-safe write signed out, but never cross-site",
    () =>
      Effect.gen(function* anonymous() {
        expect(
          yield* outcome(
            admit(requirementOf(anonymousWrite), {
              sameOrigin: true,
              signedIn: false,
            })
          )
        ).toBe("admitted");
        expect(
          yield* outcome(
            admit(requirementOf(anonymousWrite), {
              sameOrigin: false,
              signedIn: false,
            })
          )
        ).toBe("CrossSiteRequest");
      })
  );

  it.effect(
    "treats a call it cannot map to a contract as the strictest write",
    () =>
      Effect.gen(function* unmatched() {
        expect(
          yield* outcome(
            admit(strictestRequirement("POST /api/nope"), {
              sameOrigin: true,
              signedIn: false,
            })
          )
        ).toBe("SignInRequired");
      })
  );
});

const headers = (input: Readonly<Record<string, string>>) =>
  Headers.fromInput({ host: "crew.localhost:8000", ...input });

describe("isSameOrigin", () => {
  it("accepts a request without Origin, such as curl or a same-origin navigation", () => {
    expect(isSameOrigin(headers({}))).toBe(true);
    expect(
      isSameOrigin(
        headers({
          origin: "http://crew.localhost:8000",
          "sec-fetch-site": "same-origin",
        })
      )
    ).toBe(true);
  });

  it("refuses Sec-Fetch-Site cross-site even when Origin is missing", () => {
    expect(isSameOrigin(headers({ "sec-fetch-site": "cross-site" }))).toBe(
      false
    );
  });

  it("refuses an Origin naming another host, a sibling sphere included, and the opaque null origin", () => {
    expect(
      isSameOrigin(
        headers({
          origin: "http://localhost:8000",
          "sec-fetch-site": "same-site",
        })
      )
    ).toBe(false);
    expect(isSameOrigin(headers({ origin: "https://evil.example" }))).toBe(
      false
    );
    expect(isSameOrigin(headers({ origin: "null" }))).toBe(false);
  });
});

const readEvent = defineContract("readEvent", {
  annotations: { readOnly: true },
  description: "Read one event",
  failure: Schema.Never,
  http: { method: "GET", path: "/events/:slug" },
  input: Schema.Struct({ slug: Schema.String }),
  output: Schema.Void,
});

const capabilities = [write, readEvent].map((each) =>
  implement(each, () => Effect.void)
);

const request = (method: string, url: string) =>
  HttpServerRequest.fromWeb(
    new Request(`http://localhost:8000${url}`, { method })
  );

describe("contractForRequest", () => {
  it("maps POST /api/<name> and routed paths with parameters to their contract", () => {
    expect(
      Option.map(
        contractForRequest(capabilities, request("POST", "/api/enroll")),
        ({ name }) => name
      )
    ).toEqual(Option.some("enroll"));
    expect(
      Option.map(
        contractForRequest(
          capabilities,
          request("GET", "/api/events/kapitularz?x=1")
        ),
        ({ name }) => name
      )
    ).toEqual(Option.some("readEvent"));
  });

  it("finds nothing for a method or path no contract declares", () => {
    expect(
      contractForRequest(capabilities, request("GET", "/api/enroll"))
    ).toEqual(Option.none());
    expect(
      contractForRequest(capabilities, request("GET", "/api/events/a/b"))
    ).toEqual(Option.none());
  });
});
