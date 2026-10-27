import { exports } from "cloudflare:workers";
import { describe, expect, it } from "vitest";

describe("agent routes", () => {
  it.each(["parley-sphere-agent", "parley-session-agent"])(
    "accepts a socket on /agents/%s/",
    async (namespace) => {
      const response = await exports.default.fetch(`https://parley.test/agents/${namespace}/1`, {
        headers: { Origin: "http://localhost:8000", Upgrade: "websocket" },
      });

      expect(response.status).toBe(101);
      response.webSocket?.accept();
      response.webSocket?.close();
    },
  );
});
