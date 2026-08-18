// One Pi tool per discovered MCP tool — the whole point of the extension.
// Tool names arrive namespaced (zagrajmy_<tool>) so they can't shadow Pi's
// built-ins, and results pass through as text blocks the model reads as-is.

import { McpClient } from "./mcp-client";
import type { GoblinConfig } from "./config";
import type {
  McpContentBlock,
  PiExtensionContext,
  PiToolDefinition,
  PiToolResult,
} from "./types";

const asText = (blocks: McpContentBlock[]): PiToolResult["content"] =>
  blocks.map((block) => ({
    type: "text",
    text: block.type === "text" && typeof block.text === "string"
      ? block.text
      : JSON.stringify(block),
  }));

export const registerZagrajmyTools = async (
  context: PiExtensionContext,
  config: GoblinConfig,
): Promise<number> => {
  const client = new McpClient(config);
  await client.initialize();
  const tools = await client.listTools();

  for (const tool of tools) {
    const definition: PiToolDefinition = {
      name: `zagrajmy_${tool.name}`,
      description: tool.description ?? `Zagrajmy MCP tool ${tool.name}`,
      parameters: tool.inputSchema,
      execute: async (args) => {
        const result = await client.callTool(tool.name, args);
        return { content: asText(result.content), isError: result.isError ?? false };
      },
    };
    context.registerTool(definition);
  }
  return tools.length;
};
