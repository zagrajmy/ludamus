import { AppConfig } from "@zagrajmy/core";
import { Effect, Layer, Option } from "effect";
import { HttpStaticServer } from "effect/http";

export const MEDIA_PATH = "/media";

export const mediaRoutes = Layer.unwrap(
  Effect.gen(function* mediaRoutesFor() {
    const config = yield* AppConfig;

    return Option.match(config.mediaRoot, {
      onNone: () => Layer.empty,
      onSome: (root) =>
        HttpStaticServer.layer({
          cacheControl: "public, max-age=3600",
          index: undefined,
          prefix: MEDIA_PATH,
          root,
        }),
    });
  })
);
