import { Config, ConfigProvider, Context, Effect, Layer, Option } from "effect";
import type { Redacted } from "effect";

const appConfig = Config.all({
  databasePath: Config.NonEmptyString("DATABASE_PATH"),
  emailFilePath: Config.option(Config.NonEmptyString("EMAIL_FILE_PATH")),
  emailUrl: Config.option(Config.NonEmptyString("EMAIL_URL")),
  mcpToken: Config.option(Config.Redacted("MCP_TOKEN")),
  mediaRoot: Config.option(Config.NonEmptyString("MEDIA_ROOT")),
  port: Config.Port("PORT").pipe(Config.withDefault(8000)),
  publicOrigin: Config.URL("PUBLIC_ORIGIN").pipe(
    Config.withDefault(new URL("http://localhost:8000"))
  ),
  secretKey: Config.Redacted("SECRET_KEY"),
});

export interface AppSettings {
  readonly databasePath: string;
  readonly emailFilePath: Option.Option<string>;
  readonly emailUrl: Option.Option<string>;
  readonly mcpToken: Option.Option<Redacted.Redacted>;
  readonly mediaRoot: Option.Option<string>;
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

const FILEMAIL = "filemail:///";

export const mailDirectory = (config: AppSettings): Option.Option<string> =>
  Option.orElse(config.emailFilePath, () =>
    config.emailUrl.pipe(
      Option.filter((url) => url.startsWith(FILEMAIL)),
      Option.map((url) => {
        const relative = url.slice(FILEMAIL.length).split("?")[0] ?? "";
        const root = config.databasePath.slice(0, config.databasePath.lastIndexOf("/") + 1);

        return relative.startsWith("/") ? relative : `${root}${relative}`;
      })
    )
  );
