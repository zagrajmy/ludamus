import { Schema } from "effect";
import * as RpcMiddleware from "effect/rpc/RpcMiddleware";

import { CrossSiteRequest } from "./cross-site-request.js";
import { SignInRequired } from "./sign-in-required.js";
import { UnknownHost } from "./unknown-host.js";

export { CrossSiteRequest } from "./cross-site-request.js";

export { SignInRequired } from "./sign-in-required.js";

export { UnknownHost } from "./unknown-host.js";

export const Refusal = Schema.Union([
  UnknownHost,
  CrossSiteRequest,
  SignInRequired,
]);

export class Refusals extends RpcMiddleware.Service<Refusals>()(
  "@zagrajmy/capability/Refusals",
  { error: Refusal }
) {}
