# @zagrajmy/capability

rat-stack's capability package, vendored under the `@zagrajmy` scope: `defineContract`, `implement`, the catalog, approval, call watch, and the RPC, HTTP API and MCP toolkit projections.

## What this copy removed, and why

Removed: the code-mode sandbox (`sandbox-*.ts`, `layerSubprocess`, `code-mode.ts`, `to-code-mode.ts`), the CLI projection (`to-command.ts`), `actor-watch.ts` (XState actors), and their tests (`sandbox*.test.ts`, `to-code-mode`, `code-mode-context`, `to-command`), plus the template's wiki fixtures and the tests that only exercised them (`runtime-boundary`, `concurrency-ownership`). The sandbox tests spawn `node:vm` subprocesses and time out in this container; nothing in Zagrajmy uses code mode, a CLI projection or actors. Restore them from rat-stack when an app here needs them.

## What this copy added

- `toRpc(capabilities, { middleware })` attaches an `RpcMiddleware` to every RPC and drops the services it `provides` from the layer's requirements. The handlers capture the layer's build context and merge it over the request's context, so a service the middleware provides per call (the sphere from the Host header, the signed-in user) reaches the handler.
- `toHttpApi(..., { errors })` now also lets host errors leave routed endpoints, not only `POST /<name>` ones.
- Access annotations. `Annotations.anonymousSafe` (default `false`) marks a write a signed-out visitor may make. `isMutation(contract)` is `!readOnly`; `requiresSignIn(contract)` is `isMutation && !anonymousSafe`. A host applies them to every surface: a mutation must come from the same origin, and a mutation that is not anonymous-safe needs a signed-in user. Read-only contracts need neither. Mark a contract `readOnly: true` when it changes nothing, `anonymousSafe: true` only when the Django view it ports accepts anonymous users (the anonymous proposal form, for example).
- Refusals every projection may answer, exported from the browser-safe `rpc-group` entry: `UnknownHost` (404), `CrossSiteRequest` (403), `SignInRequired` (401), their union `Refusal`, and `Refusals`, a client-side `RpcMiddleware` that declares them so a browser `RpcClient` decodes them as typed failures.

# HTTP routes, provide hooks, and failures

`toHttpApi` serves a contract with an `http` route at that method and path. Each `:name` path segment reads the input field of that name, and a segment that names no input field is a type error in `defineContract` (and a throw in `toHttpApi` for contracts only known as `AnyContract`). Without `http`, a contract answers `POST /<name>` with a JSON body.

There is no raw middleware option. A host reaches into a request only through two hooks:

- **`provide`:** a list of `{ tag, failure, from }`. `from(request)` either succeeds with the service for `tag`, which the route's handler then reads, or fails with a value of `failure`, a declared schema that is encoded like any other failure (its `httpApiStatus` annotation is the status, and `HttpApiSchema.encodeToWithHeaders` can add headers such as `WWW-Authenticate`). A hook cannot answer a response. When it succeeds, decode, handler and encode always run. It is the HTTP twin of `CurrentPersonMiddleware` in `packages/auth`. The projection's layer requires whatever the hooks' `from` functions require, and no longer requires the services the hooks provide.
- **`decodeRefusal`:** renders a request the route could not decode (query, params, payload or headers) as the host's own body, through Effect's `HttpApiMiddleware.layerSchemaErrorTransform`. Without it, a decode refusal is Effect's empty 400. It never sees response encoding errors.

A handler's failure leaves only through the contract's failure schema. A union failure answers each member's own `httpApiStatus` (422 when a member has none), and encoding drops fields the member does not declare. A failure the schema does not declare is a 500 with an empty body.
