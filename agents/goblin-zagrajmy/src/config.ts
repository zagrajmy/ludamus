// Environment contract for the extension. The token is resolved on every
// call, never cached at module scope: the secrets-broker Actor injects
// short-lived credentials into the isolate's environment, so caching would
// keep a revoked token alive.

export type GoblinConfig = {
  mcpUrl: string;
  readToken: () => string;
};

const requireEnv = (env: Record<string, string | undefined>, name: string): string => {
  const value = env[name];
  if (!value) {
    throw new Error(`goblin-zagrajmy: required environment variable ${name} is not set`);
  }
  return value;
};

export const readConfig = (env: Record<string, string | undefined>): GoblinConfig => ({
  mcpUrl: requireEnv(env, "ZAGRAJMY_MCP_URL"),
  readToken: () => requireEnv(env, "ZAGRAJMY_MCP_TOKEN"),
});
