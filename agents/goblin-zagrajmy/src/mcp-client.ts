// Thin JSON-RPC client for the MCP streamable HTTP transport. Speaks only
// what the bridge needs — initialize, tools/list, tools/call — directly over
// fetch, so the isolate bundle carries no SDK. Server-side, the endpoint is
// Django's /mcp/ (docs/agents/mcp.md).

import type { GoblinConfig } from "./config";
import type { JsonRpcResponse, McpToolCallResult, McpToolDescriptor } from "./types";

const PROTOCOL_VERSION = "2025-06-18";

export class McpError extends Error {
  constructor(
    readonly method: string,
    message: string,
  ) {
    super(`MCP ${method}: ${message}`);
  }
}

export class McpClient {
  #config: GoblinConfig;
  #nextId = 1;
  #sessionId: string | null = null;

  constructor(config: GoblinConfig) {
    this.#config = config;
  }

  async initialize(): Promise<void> {
    await this.#call("initialize", {
      protocolVersion: PROTOCOL_VERSION,
      capabilities: {},
      clientInfo: { name: "goblin-zagrajmy", version: "0.1.0" },
    });
    await this.#notify("notifications/initialized");
  }

  async listTools(): Promise<McpToolDescriptor[]> {
    const result = await this.#call<{ tools: McpToolDescriptor[] }>("tools/list", {});
    return result.tools;
  }

  async callTool(name: string, args: Record<string, unknown>): Promise<McpToolCallResult> {
    return this.#call<McpToolCallResult>("tools/call", { name, arguments: args });
  }

  async #call<T>(method: string, params: Record<string, unknown>): Promise<T> {
    const response = await this.#post({
      jsonrpc: "2.0",
      id: this.#nextId++,
      method,
      params,
    });
    const sessionId = response.headers.get("mcp-session-id");
    if (sessionId) this.#sessionId = sessionId;

    const body = (await response.json()) as JsonRpcResponse<T>;
    if ("error" in body) {
      throw new McpError(method, body.error.message);
    }
    return body.result;
  }

  async #notify(method: string): Promise<void> {
    await this.#post({ jsonrpc: "2.0", method });
  }

  async #post(payload: Record<string, unknown>): Promise<Response> {
    const headers: Record<string, string> = {
      "content-type": "application/json",
      accept: "application/json, text/event-stream",
      authorization: `Bearer ${this.#config.readToken()}`,
      "mcp-protocol-version": PROTOCOL_VERSION,
    };
    if (this.#sessionId) headers["mcp-session-id"] = this.#sessionId;

    const response = await fetch(this.#config.mcpUrl, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });
    if (!response.ok && response.status !== 202) {
      throw new McpError(String(payload["method"]), `HTTP ${response.status}`);
    }
    return response;
  }
}
