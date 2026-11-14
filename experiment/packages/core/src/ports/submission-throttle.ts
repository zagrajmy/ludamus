import { Clock, Context, Effect, Layer, Ref } from "effect";

export class SubmissionThrottle extends Context.Service<
  SubmissionThrottle,
  {
    readonly reserve: (options: {
      readonly key: string;
      readonly seconds: number;
    }) => Effect.Effect<boolean>;
  }
>()("@zagrajmy/core/SubmissionThrottle") {
  static readonly memory = Layer.effect(
    SubmissionThrottle,
    Effect.gen(function* makeMemoryThrottle() {
      const expiries = yield* Ref.make<ReadonlyMap<string, number>>(new Map());

      const reserve = Effect.fn("SubmissionThrottle.reserve")(function* reserve(
        options: Readonly<{ key: string; seconds: number }>
      ) {
        const now = yield* Clock.currentTimeMillis;

        return yield* Ref.modify(expiries, (held) => {
          const live = new Map(
            [...held].filter(([, expiresAt]) => expiresAt > now)
          );

          if (live.has(options.key)) {
            return [false, live];
          }

          live.set(options.key, now + options.seconds * 1000);

          return [true, live];
        });
      });

      return SubmissionThrottle.of({ reserve });
    })
  );
}
