import { Schema } from "effect";

export const DashboardFlags = Schema.Struct({
  hostsCount: Schema.Int,
  pendingProposals: Schema.Int,
  roomsCount: Schema.Int,
  scheduledSessions: Schema.Int,
  totalProposals: Schema.Int,
  totalSessions: Schema.Int,
});

export type DashboardFlags = typeof DashboardFlags.Type;
