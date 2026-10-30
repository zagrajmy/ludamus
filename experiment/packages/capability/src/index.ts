export { CallWatch, type Around, type CallWatchService } from "./call-watch.js";

export {
  defineContract,
  failureSchemaOf,
  type Annotations,
  type AnyCapability,
  type AnyContract,
  type ApprovalRequirement,
  type Capability,
  type Contract,
  type ContractFailureOf,
  type ContractOf,
  type DefineContractOptions,
  type FailureOf,
  type FailureSchemaOf,
  type HttpMethod,
  type HttpRoute,
  type HttpRouteOf,
  type InputOf,
  type InputSchema,
  type NameOf,
  type OutputOf,
  type PathParamNames,
  type PlainSchema,
  type RequirementsOf,
  type RouteParamsCheck,
} from "./contract.js";

export { aroundHandlers, implement } from "./implement.js";

export { Approval, ApprovalDenied, type ApprovalService } from "./approval.js";

export {
  searchCatalog,
  signatureOf,
  toCatalog,
  toTypeScript,
  type Catalog,
  type CatalogEntry,
  type SearchMatch,
} from "./catalog.js";

export {
  GROUP as HTTP_API_GROUP,
  toHttpApi,
  type HttpApiProjection,
  type HttpApiProjectionOptions,
  type AnyHttpProvide,
  type CheckedHook,
  type CheckedHooks,
  type HttpProvide,
  type MiddlewareOf,
  type ProvideMiddleware,
} from "./to-http-api.js";

export {
  toToolkit,
  type ToolkitProjection,
  type ToolsOf,
} from "./to-toolkit.js";

export {
  toRpc,
  type ContractsOf,
  type RpcProjection,
  type RpcProjectionOptions,
} from "./to-rpc.js";

export {
  toRpcGroup,
  type RpcGroupProjection,
  type RpcOf,
  type RpcsOf,
} from "./to-rpc-group.js";

export { isMutation, requiresSignIn } from "./access.js";

export {
  CrossSiteRequest,
  Refusal,
  Refusals,
  SignInRequired,
  UnknownHost,
} from "./refusal.js";
