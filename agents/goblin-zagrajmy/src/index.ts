// Extension entry point. Pi calls this with its extension context; the
// bridge does the rest. Config comes from the isolate's environment, where
// the secrets-broker Actor injects ZAGRAJMY_MCP_URL / ZAGRAJMY_MCP_TOKEN.

import { readConfig } from "./config";
import { registerZagrajmyTools } from "./bridge";
import type { PiExtensionContext } from "./types";

export const activate = async (
  context: PiExtensionContext,
  env: Record<string, string | undefined>,
): Promise<void> => {
  const config = readConfig(env);
  await registerZagrajmyTools(context, config);
};
