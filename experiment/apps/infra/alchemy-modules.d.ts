declare module "alchemy" {
  import type { Effect, Layer } from "effect";

  export interface Secret {
    readonly name: string;
  }

  export interface StackOptions<Providers> {
    readonly providers: Layer.Layer<Providers>;
    readonly state: Layer.Layer<never>;
  }

  export interface StackDefinition<Output> {
    readonly name: string;
    readonly program: Effect.Effect<Output>;
  }

  export const secret: (name: string) => Secret;

  export const Stack: <Providers, Output>(
    name: string,
    options: StackOptions<Providers>,
    program: Effect.Effect<Output, never, Providers>
  ) => StackDefinition<Output>;
}

declare module "@alchemy.run/cloudflare" {
  import type { Effect, Layer } from "effect";
  import type { Secret } from "alchemy";

  export interface CloudflareProviders {
    readonly accountId: string;
  }

  export interface HyperdriveConnection {
    readonly id: string;
  }

  export interface WorkerOutput {
    readonly name: string;
    readonly url: string;
  }

  export interface WebsiteOutput {
    readonly name: string;
    readonly url: string;
  }

  export const providers: () => Layer.Layer<CloudflareProviders>;

  export const state: () => Layer.Layer<never>;

  export const Hyperdrive: {
    readonly Connection: (
      name: string,
      options: { readonly origin: Secret }
    ) => Effect.Effect<HyperdriveConnection, never, CloudflareProviders>;
  };

  export const Worker: (
    name: string,
    options: {
      readonly bindings: Readonly<Record<string, HyperdriveConnection | Secret>>;
      readonly entrypoint: string;
    }
  ) => Effect.Effect<WorkerOutput, never, CloudflareProviders>;

  export const Website: {
    readonly Foldkit: (
      name: string,
      options: {
        readonly assets: {
          readonly htmlHandling: "drop-trailing-slash";
          readonly runWorkerFirst: readonly string[];
        };
        readonly env: Readonly<Record<string, WorkerOutput>>;
        readonly rootDir: string;
      }
    ) => Effect.Effect<WebsiteOutput, never, CloudflareProviders>;
  };
}
