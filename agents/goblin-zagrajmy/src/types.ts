// Structural types for the slice of Pi's extension API this package touches.
// Local until the real Pi dependency is added (see README); shaped after
// pi's tool registration surface so the swap is mechanical.

export type JsonSchema = {
  type?: string;
  properties?: Record<string, unknown>;
  required?: string[];
  [key: string]: unknown;
};

export type PiToolResult = {
  content: { type: "text"; text: string }[];
  isError?: boolean;
};

export type PiToolDefinition = {
  name: string;
  description: string;
  parameters: JsonSchema;
  execute: (args: Record<string, unknown>) => Promise<PiToolResult>;
};

export type PiExtensionContext = {
  registerTool: (tool: PiToolDefinition) => void;
};

// MCP wire types — the subset of the 2025-06-18 schema the thin client
// speaks: initialize, tools/list, tools/call.

export type McpToolDescriptor = {
  name: string;
  description?: string;
  inputSchema: JsonSchema;
};

export type McpContentBlock = {
  type: string;
  text?: string;
  [key: string]: unknown;
};

export type McpToolCallResult = {
  content: McpContentBlock[];
  isError?: boolean;
};

export type JsonRpcResponse<T> =
  | { jsonrpc: "2.0"; id: number; result: T }
  | { jsonrpc: "2.0"; id: number; error: { code: number; message: string } };
