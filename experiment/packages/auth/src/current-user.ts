import type { UserRow } from "@zagrajmy/database";
import { Context } from "effect";
import type { Option } from "effect";

export class CurrentUser extends Context.Service<
  CurrentUser,
  Option.Option<UserRow>
>()("@zagrajmy/auth/CurrentUser") {}
