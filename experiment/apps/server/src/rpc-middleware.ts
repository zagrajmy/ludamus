import { CurrentUser } from "@zagrajmy/auth";
import type { AnyCapability, AnyContract } from "@zagrajmy/capability/contract";
import { Refusal } from "@zagrajmy/capability/refusal";
import { capabilities } from "@zagrajmy/core";
import { Context, Effect, Layer, Option } from "effect";
import * as RpcMiddleware from "effect/rpc/RpcMiddleware";

import { admit, requirementOf, strictestRequirement } from "./access-policy.js";
import { RequestContext, isSameOrigin } from "./request-context.js";
import type { RequestServices } from "./request-context.js";

export class RequestContextMiddleware extends RpcMiddleware.Service<
  RequestContextMiddleware,
  { provides: RequestServices }
>()("@zagrajmy/server/RequestContextMiddleware", { error: Refusal }) {}

export const contractsByName = (all: readonly AnyCapability[]) =>
  new Map<string, AnyContract>(
    all.map(({ contract }) => [contract.name, contract])
  );

const contracts = contractsByName(capabilities);

export const requestContextMiddleware = Layer.effect(
  RequestContextMiddleware,
  Effect.gen(function* makeRequestContextMiddleware() {
    const context = yield* RequestContext;

    return RequestContextMiddleware.of((effect, { headers, rpc }) =>
      Effect.gen(function* provideRequestContext() {
        const services = yield* context.services(headers);
        const contract = Option.fromNullishOr(contracts.get(rpc._tag));

        yield* admit(
          Option.match(contract, {
            onNone: () => strictestRequirement(rpc._tag),
            onSome: requirementOf,
          }),
          {
            sameOrigin: isSameOrigin(headers),
            signedIn: Option.isSome(Context.get(services, CurrentUser)),
          }
        );

        return yield* Effect.provideContext(effect, services);
      })
    );
  })
);
