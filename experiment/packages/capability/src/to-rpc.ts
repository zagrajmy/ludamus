// @effect-diagnostics anyUnknownInErrorContext:off unsafeEffectTypeAssertion:off missingEffectContext:off -- This projection erases each capability's schema and requirement types while building the heterogeneous RpcGroup and recovers them at its public boundary.
import type { Layer } from "effect";
import { Effect } from "effect";
import type * as Rpc from "effect/rpc/Rpc";
import type * as RpcGroup from "effect/rpc/RpcGroup";
import type * as RpcMiddleware from "effect/rpc/RpcMiddleware";

import type { AnyCapability, ContractOf, RequirementsOf } from "./contract.js";
import { toRpcGroup } from "./to-rpc-group.js";
import type { RpcsOf } from "./to-rpc-group.js";

export type ContractsOf<Caps extends readonly AnyCapability[]> = {
  readonly [K in keyof Caps]: ContractOf<Caps[K]>;
};

type ProjectedRpcs<
  Caps extends readonly AnyCapability[],
  Middleware extends RpcMiddleware.AnyService,
> = Rpc.AddMiddleware<RpcsOf<ContractsOf<Caps>>[number], Middleware>;

export interface RpcProjection<
  Caps extends readonly AnyCapability[],
  Middleware extends RpcMiddleware.AnyService = never,
> {
  readonly group: RpcGroup.RpcGroup<ProjectedRpcs<Caps, Middleware>>;
  readonly layer: Layer.Layer<
    Rpc.ToHandler<ProjectedRpcs<Caps, Middleware>>,
    never,
    Exclude<
      RequirementsOf<Caps>,
      RpcMiddleware.Provides<Middleware["Identifier"]>
    >
  >;
}

export interface RpcProjectionOptions<
  Middleware extends RpcMiddleware.AnyService,
> {
  readonly middleware?: Middleware | undefined;
}

export const toRpc = <
  const Caps extends readonly AnyCapability[],
  Middleware extends RpcMiddleware.AnyService = never,
>(
  capabilities: Caps,
  options?: RpcProjectionOptions<Middleware>
): RpcProjection<Caps, Middleware> => {
  const contracts = capabilities.map((capability) => capability.contract);
  // SAFETY: mapping preserves the capability order and each implementation exposes its exact contract.
  // oxlint-disable-next-line typescript/no-unsafe-type-assertion
  const contractTuple = contracts as ContractsOf<Caps>;
  const projected = toRpcGroup(contractTuple).group;

  const group =
    options?.middleware === undefined
      ? projected
      : projected.middleware(options.middleware);

  const built = projected.toLayer(
    Effect.gen(function* buildHandlers() {
      const context = yield* Effect.context<RequirementsOf<Caps>>();

      const handlers: Record<
        string,
        (
          // oxlint-disable-next-line anti-slop/no-unknown-parameters -- RpcGroup invokes this only after decoding the RPC payload schema.
          payload: unknown
        ) => Effect.Effect<unknown, unknown>
      > = {};

      for (const capability of capabilities) {
        // SAFETY: the server decodes this RPC's payload schema before dispatch, and the capability's requirements are included in RequirementsOf<Caps>.
        // oxlint-disable-next-line typescript/no-unsafe-type-assertion
        const run = capability.handler as (
          // oxlint-disable-next-line anti-slop/no-unknown-parameters -- RpcGroup invokes this only after decoding the RPC payload schema.
          input: unknown
        ) => Effect.Effect<unknown, unknown, RequirementsOf<Caps>>;

        handlers[capability.contract.name] = (payload) =>
          run(payload).pipe(Effect.provideContext(context));
      }

      // SAFETY: the loop uses each capability contract's exact name, and its handler dispatches through that contract's schema-backed RPC definition.
      // oxlint-disable-next-line typescript/no-unsafe-type-assertion, anti-slop/no-chained-type-assertions -- This heterogeneous projection recovers the mapped handlers after the runtime name-indexed loop.
      return handlers as unknown as RpcGroup.HandlersFrom<
        RpcsOf<ContractsOf<Caps>>[number]
      >;
    })
  );

  // SAFETY: the group contains exactly the RPCs derived from the capability contracts, and the handlers capture but do not provide their requirements; the services the middleware provides reach each handler per request, because the captured build context is merged over the request's context rather than replacing it.
  // oxlint-disable-next-line typescript/no-unsafe-type-assertion, anti-slop/no-chained-type-assertions -- The middleware variant changes only the RPC middleware set, which the runtime loop never reads.
  const layer = built as unknown as RpcProjection<Caps, Middleware>["layer"];

  // SAFETY: adding middleware keeps every RPC's tag, key and schemas; ProjectedRpcs names the same RPCs with the middleware recorded.
  // oxlint-disable-next-line typescript/no-unsafe-type-assertion, anti-slop/no-chained-type-assertions -- The conditional middleware branch erases the RPC union that ProjectedRpcs restores.
  const typedGroup = group as unknown as RpcGroup.RpcGroup<
    ProjectedRpcs<Caps, Middleware>
  >;

  return { group: typedGroup, layer };
};
