import { Refusals, toRpcGroup } from "@zagrajmy/capability/rpc-group";
import { contracts } from "@zagrajmy/core/contracts";
import { Context, Layer } from "effect";
import type { Effect } from "effect";
import { FetchHttpClient } from "effect/http";
import { RpcClient, RpcSerialization } from "effect/rpc";

export const RPC_URL = "/rpc";

const group = toRpcGroup(contracts).group.middleware(Refusals);

const transport = RpcClient.layerProtocolHttp({ url: RPC_URL }).pipe(
  Layer.provide(FetchHttpClient.layer),
  Layer.provide(
    Layer.succeed(FetchHttpClient.RequestInit, { credentials: "same-origin" })
  ),
  Layer.provide(RpcSerialization.layerJson)
);

const make = RpcClient.make(group);

export class Backend extends Context.Service<
  Backend,
  Effect.Success<typeof make>
>()("@zagrajmy/web/client/Backend") {
  static readonly layer = Layer.effect(Backend, make).pipe(
    Layer.provide(transport)
  );
}

const keepAliveTransport = RpcClient.layerProtocolHttp({ url: RPC_URL }).pipe(
  Layer.provide(FetchHttpClient.layer),
  Layer.provide(
    Layer.succeed(FetchHttpClient.RequestInit, {
      credentials: "same-origin",
      keepalive: true,
    })
  ),
  Layer.provide(RpcSerialization.layerJson)
);

export const keepAliveBackend = Layer.effect(Backend, make).pipe(
  Layer.provide(keepAliveTransport)
);
