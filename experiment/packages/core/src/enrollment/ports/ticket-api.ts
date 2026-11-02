import { Context } from "effect";
import type { Effect } from "effect";
import type { MembershipApiError } from "../membership-api-error.js";

export class TicketApi extends Context.Service<
  TicketApi,
  {
    readonly fetchMembershipCount: (query: {
      readonly eventId: number;
      readonly email: string;
    }) => Effect.Effect<number, MembershipApiError>;
  }
>()("@zagrajmy/core/enrollment/TicketApi") {}
