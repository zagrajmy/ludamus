import { Config, ConfigProvider, Context, Effect, Layer, Option } from "effect";
import type { Redacted } from "effect";

const appConfig = Config.all({
  databasePath: Config.NonEmptyString("DATABASE_PATH"),
  mcpToken: Config.option(Config.Redacted("MCP_TOKEN")),
  port: Config.Port("PORT").pipe(Config.withDefault(8000)),
  publicOrigin: Config.URL("PUBLIC_ORIGIN").pipe(
    Config.withDefault(new URL("http://localhost:8000"))
  ),
  secretKey: Config.Redacted("SECRET_KEY"),
});

export interface AppSettings {
  readonly databasePath: string;
  readonly mcpToken: Option.Option<Redacted.Redacted>;
  readonly port: number;
  readonly publicOrigin: URL;
  readonly secretKey: Redacted.Redacted;
}

export class AppConfig extends Context.Service<AppConfig, AppSettings>()(
  "@zagrajmy/core/AppConfig"
) {
  static readonly layer = Layer.effect(
    AppConfig,
    Effect.gen(function* readAppConfig() {
      return AppConfig.of(yield* appConfig);
    })
  );
}

export const configLayer = (values: Readonly<Record<string, string>>) =>
  AppConfig.layer.pipe(
    Layer.provide(ConfigProvider.layer(ConfigProvider.fromEnvRecord(values)))
  );

export const mcpEnabled = (config: AppSettings) =>
  Option.isSome(config.mcpToken);
