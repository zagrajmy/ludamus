import { describe, expect, it } from "@effect/vitest";
import { Context, Effect, Layer, Option, Schema } from "effect";
import { RpcTest } from "effect/rpc";
import * as RpcMiddleware from "effect/rpc/RpcMiddleware";

import {
  SignInRequired,
  defineContract,
  implement,
  isMutation,
  requiresSignIn,
  toRpc,
} from "../src/index.js";

interface CallerService {
  readonly name: string;
}

const Caller = Context.Service<CallerService, CallerService>(
  "@zagrajmy/capability/test/RpcCaller"
);

class CallerFromHeaders extends RpcMiddleware.Service<
  CallerFromHeaders,
  { provides: CallerService }
>()("@zagrajmy/capability/test/CallerFromHeaders", {
  error: SignInRequired,
}) {}

const whoAmIContract = defineContract("whoAmI", {
  annotations: { readOnly: true },
  description: "Name the caller the host resolved",
  failure: Schema.Never,
  input: Schema.Struct({}),
  output: Schema.Struct({ name: Schema.String }),
});

const whoAmI = implement(whoAmIContract, () =>
  Effect.gen(function* whoAmIHandler() {
    const { name } = yield* Caller;

    return { name };
  })
);

const projection = toRpc([whoAmI], { middleware: CallerFromHeaders });

const middlewareFor = (name: Option.Option<string>) =>
  Layer.succeed(
    CallerFromHeaders,
    CallerFromHeaders.of((effect, { rpc }) =>
      Option.match(name, {
        onNone: () =>
          Effect.fail(new SignInRequired({ capabilityName: rpc._tag })),
        onSome: (resolved) =>
          Effect.provideService(effect, Caller, { name: resolved }),
      })
    )
  );

const clientWith = (name: Option.Option<string>) =>
  RpcTest.makeClient(projection.group).pipe(
    Effect.provide(Layer.merge(projection.layer, middlewareFor(name)))
  );

describe("toRpc with middleware", () => {
  it.effect(
    "reaches the handler with the service the middleware provides per call",
    () =>
      Effect.gen(function* providedPerCall() {
        const client = yield* clientWith(Option.some("ola"));

        expect(yield* client.whoAmI({})).toEqual({ name: "ola" });
      })
  );

  it.effect(
    "answers the middleware's declared refusal without running the handler",
    () =>
      Effect.gen(function* refused() {
        const client = yield* clientWith(Option.none());
        const error = yield* client.whoAmI({}).pipe(Effect.flip);

        expect(Schema.is(SignInRequired)(error)).toBe(true);
      })
  );
});

const write = (anonymousSafe: boolean) =>
  defineContract("write", {
    annotations: { anonymousSafe },
    description: "A write",
    failure: Schema.Never,
    input: Schema.Struct({}),
    output: Schema.Void,
  });

describe("access annotations", () => {
  it("treats every contract that is not read-only as a mutation", () => {
    expect(isMutation(whoAmIContract)).toBe(false);
    expect(isMutation(write(false))).toBe(true);
  });

  it("asks for sign-in on writes unless the contract is anonymous-safe", () => {
    expect(requiresSignIn(whoAmIContract)).toBe(false);
    expect(requiresSignIn(write(false))).toBe(true);
    expect(requiresSignIn(write(true))).toBe(false);
  });
});
