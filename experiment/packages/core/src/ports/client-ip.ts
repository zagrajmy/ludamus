import { Context } from "effect";
import type { Option } from "effect";

export class ClientIp extends Context.Service<
  ClientIp,
  Option.Option<string>
>()("@zagrajmy/core/ClientIp") {}
