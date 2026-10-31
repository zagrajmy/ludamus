import { NodeServices } from "@effect/platform-node";
import { SessionResolverLive } from "@zagrajmy/auth";
import { AppConfig } from "@zagrajmy/core";
import { DatabaseLive } from "@zagrajmy/database";
import { FeedStoreLive } from "@zagrajmy/database/feed-store";
import { LandingStoreLive } from "@zagrajmy/database/landing-store";
import { ShellStoreLive } from "@zagrajmy/database/shell-store";
import { Layer, ManagedRuntime } from "effect";

const PageStoresLive = Layer.mergeAll(
  FeedStoreLive,
  LandingStoreLive,
  ShellStoreLive
);

export const ServerLive = Layer.mergeAll(
  SessionResolverLive,
  PageStoresLive
).pipe(
  Layer.provideMerge(DatabaseLive),
  Layer.provideMerge(AppConfig.layer),
  Layer.provideMerge(NodeServices.layer)
);

export const serverRuntime = ManagedRuntime.make(ServerLive);
