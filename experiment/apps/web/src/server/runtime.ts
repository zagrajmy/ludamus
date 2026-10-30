import { NodeServices } from "@effect/platform-node";
import { SessionResolverLive } from "@zagrajmy/auth";
import { DatabaseLive } from "@zagrajmy/database";
import { Layer, ManagedRuntime } from "effect";

export const ServerLive = SessionResolverLive.pipe(
  Layer.provideMerge(DatabaseLive),
  Layer.provideMerge(NodeServices.layer)
);

export const serverRuntime = ManagedRuntime.make(ServerLive);
