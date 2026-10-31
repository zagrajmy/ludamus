import { CurrentUser } from "@zagrajmy/auth";
import type { AnyCapability } from "@zagrajmy/capability/contract";
import { toHttpApi } from "@zagrajmy/capability/http-api";
import { aroundHandlers } from "@zagrajmy/capability/implement";
import { CrossSiteRequest, SignInRequired } from "@zagrajmy/capability/refusal";
import { toRpc } from "@zagrajmy/capability/rpc";
import { toToolkit } from "@zagrajmy/capability/toolkit";
import {
  AppConfig,
  CurrentSphere,
  ClientIp,
  CurrentViewer,
  capabilities,
  mcpEnabled,
} from "@zagrajmy/core";
import { CurrentLocale, DEFAULT_LOCALE } from "@zagrajmy/i18n";
import { Context, Effect, Layer, Option } from "effect";
import { McpProtocol, McpServer } from "effect/ai";
import { HttpRouter, HttpServerResponse } from "effect/http";
import { HttpApiBuilder, HttpApiScalar } from "effect/http-api";
import { RpcSerialization, RpcServer } from "effect/rpc";

import { refuseWithoutUser } from "./access-policy.js";
import { API_PREFIX, httpHooks } from "./http-hooks.js";
import { MCP_PATH } from "./mcp-gate.js";
import { RequestContext } from "./request-context.js";
import {
  RequestContextMiddleware,
  requestContextMiddleware,
} from "./rpc-middleware.js";

export const RPC_PATH = "/rpc";

export const OPENAPI_PATH = "/openapi.json";

export const DOCS_PATH = "/docs";

const VERSION = "0.1.0";

export const rpc = toRpc(capabilities, {
  middleware: RequestContextMiddleware,
});

export const tools = toToolkit(
  aroundHandlers(capabilities, (contract, _input, run) =>
    refuseWithoutUser(contract, run)
  )
);

const rpcRoutes = RpcServer.layerHttp({
  group: rpc.group,
  path: RPC_PATH,
  protocol: "http",
}).pipe(
  Layer.provide(rpc.layer),
  Layer.provide(requestContextMiddleware),
  Layer.provide(RpcSerialization.layerJson)
);

export const httpApiFor = <
  const Caps extends readonly [AnyCapability, ...AnyCapability[]],
>(
  all: Caps,
  context: RequestContext["Service"]
) => {
  const http = toHttpApi("Zagrajmy", all, {
    errors: [CrossSiteRequest, SignInRequired],
    prefix: API_PREFIX,
    provide: httpHooks(context, all),
  });

  return {
    api: http.api,
    openApi: http.openApi,
    routes: HttpApiBuilder.layer(http.api).pipe(Layer.provide(http.layer)),
  };
};

const httpRoutes = Layer.unwrap(
  Effect.gen(function* projectHttpApi() {
    const http = httpApiFor(capabilities, yield* RequestContext);
    const document = HttpServerResponse.jsonUnsafe(http.openApi());

    return Layer.mergeAll(
      http.routes,
      HttpApiScalar.layer(http.api, { path: DOCS_PATH }),
      HttpRouter.add("GET", OPENAPI_PATH, document)
    );
  })
);

const mcpServices = Layer.effectContext(
  Effect.gen(function* mcpServices() {
    const config = yield* AppConfig;
    const context = yield* RequestContext;
    const sphere = yield* context.sphere(config.publicOrigin.host);

    return Context.make(CurrentSphere, sphere).pipe(
      Context.add(CurrentUser, Option.none()),
      Context.add(CurrentViewer, Option.none()),
      Context.add(CurrentLocale, DEFAULT_LOCALE),
      Context.add(ClientIp, Option.none())
    );
  })
);

const mcpRoutes = McpServer.toolkit(tools.toolkit).pipe(
  Layer.provideMerge(tools.layer),
  Layer.provide(
    McpServer.layerHttp({
      name: "zagrajmy",
      path: MCP_PATH,
      protocols: [McpProtocol.v2025_06_18, McpProtocol.v2025_03_26],
      version: VERSION,
    })
  ),
  Layer.provide(mcpServices)
);

const mcpDisabled = HttpRouter.add(
  "*",
  MCP_PATH,
  HttpServerResponse.text(
    "MCP is disabled on this server: set MCP_TOKEN to enable it.",
    {
      status: 404,
    }
  )
);

export const surfaces = Layer.unwrap(
  Effect.gen(function* surfacesFor() {
    const config = yield* AppConfig;

    return Layer.mergeAll(
      rpcRoutes,
      httpRoutes,
      mcpEnabled(config) ? mcpRoutes : mcpDisabled
    );
  })
);
