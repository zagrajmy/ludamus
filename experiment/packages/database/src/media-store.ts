import { AppConfig, StoreError } from "@zagrajmy/core";
import { MediaStore } from "@zagrajmy/core/ports/media-store";
import { Effect, FileSystem, Layer, Option, Path, Random } from "effect";

const HEX = "0123456789abcdef";

const uploadName = Effect.gen(function* uploadName() {
  const digits = yield* Effect.forEach(Array.from({ length: 32 }), () =>
    Random.nextIntBetween(0, HEX.length - 1)
  );

  return digits.map((digit) => HEX.charAt(digit)).join("");
});

export const MediaStoreLive = Layer.effect(
  MediaStore,
  Effect.gen(function* makeMediaStore() {
    const config = yield* AppConfig;
    const files = yield* FileSystem.FileSystem;
    const path = yield* Path.Path;

    const save = Effect.fn("MediaStore.save")(function* save(options: {
      readonly bytes: Uint8Array;
      readonly folder: string;
      readonly suffix: string;
    }) {
      const root = yield* Option.match(config.mediaRoot, {
        onNone: () =>
          Effect.fail(
            new StoreError({
              operation: "MediaStore.save",
              reason: "MediaRootUnset",
            })
          ),
        onSome: Effect.succeed,
      });

      const stored = `${options.folder}/${yield* uploadName}${options.suffix}`;
      const target = path.join(root, stored);

      yield* files
        .makeDirectory(path.dirname(target), { recursive: true })
        .pipe(
          Effect.andThen(files.writeFile(target, options.bytes)),
          Effect.mapError(
            (cause) =>
              new StoreError({
                operation: "MediaStore.save",
                reason: cause._tag,
              })
          )
        );

      return stored;
    });

    return MediaStore.of({ save });
  })
);
