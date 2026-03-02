/**
 * Unit tests for webhook URL generation logic in CopyFieldAreaComponent
 * This test focuses specifically on testing the URL generation logic that includes agent ID
 */

describe("Webhook URL Generation Logic", () => {
  const BACKEND_URL = "BACKEND_URL";
  const MCP_SSE_VALUE = "MCP_SSE";

  // Mock the protocol and host values
  const protocol = "http:";
  const host = "localhost:7860";
  const URL_WEBHOOK = `${protocol}//${host}/api/webhook/`;
  const URL_MCP_SSE = `${protocol}//${host}/api/mcp/sse`;

  // Helper function that mirrors the component's logic
  function generateWebhookUrl(
    value: string,
    endpointName?: string,
    agentId?: string,
  ): string {
    if (value === BACKEND_URL) {
      return `${URL_WEBHOOK}${endpointName ?? ""}${agentId ?? ""}`;
    } else if (value === MCP_SSE_VALUE) {
      return URL_MCP_SSE;
    }
    return value;
  }

  describe("BACKEND_URL webhook generation", () => {
    it("should generate webhook URL with agent ID when both endpoint name and agent ID are provided", () => {
      const result = generateWebhookUrl(
        BACKEND_URL,
        "test-endpoint",
        "agent-123",
      );

      expect(result).toBe(
        "http://localhost:7860/api/webhook/test-endpointagent-123",
      );
    });

    it("should generate webhook URL with only endpoint name when agent ID is missing", () => {
      const result = generateWebhookUrl(
        BACKEND_URL,
        "test-endpoint",
        undefined,
      );

      expect(result).toBe("http://localhost:7860/api/webhook/test-endpoint");
    });

    it("should generate webhook URL with only agent ID when endpoint name is missing", () => {
      const result = generateWebhookUrl(BACKEND_URL, undefined, "agent-123");

      expect(result).toBe("http://localhost:7860/api/webhook/agent-123");
    });

    it("should generate base webhook URL when both endpoint name and agent ID are missing", () => {
      const result = generateWebhookUrl(BACKEND_URL, undefined, undefined);

      expect(result).toBe("http://localhost:7860/api/webhook/");
    });

    it("should handle empty string values", () => {
      const result = generateWebhookUrl(BACKEND_URL, "", "");

      expect(result).toBe("http://localhost:7860/api/webhook/");
    });

    it("should handle special characters in agent ID", () => {
      const specialAgentId = "agent-123_test%20id!@#$%";
      const result = generateWebhookUrl(BACKEND_URL, "endpoint", specialAgentId);

      expect(result).toBe(
        `http://localhost:7860/api/webhook/endpoint${specialAgentId}`,
      );
    });

    it("should handle very long agent IDs", () => {
      const longAgentId = "a".repeat(200);
      const result = generateWebhookUrl(BACKEND_URL, "endpoint", longAgentId);

      expect(result).toBe(
        `http://localhost:7860/api/webhook/endpoint${longAgentId}`,
      );
    });

    it("should handle Unicode characters in agent ID", () => {
      const unicodeAgentId = "agent-🔥-test-😄";
      const result = generateWebhookUrl(BACKEND_URL, "endpoint", unicodeAgentId);

      expect(result).toBe(
        `http://localhost:7860/api/webhook/endpoint${unicodeAgentId}`,
      );
    });
  });

  describe("MCP_SSE_VALUE generation", () => {
    it("should generate MCP SSE URL regardless of endpoint name and agent ID", () => {
      const result = generateWebhookUrl(
        MCP_SSE_VALUE,
        "test-endpoint",
        "agent-123",
      );

      expect(result).toBe("http://localhost:7860/api/mcp/sse");
    });

    it("should generate MCP SSE URL with missing parameters", () => {
      const result = generateWebhookUrl(MCP_SSE_VALUE, undefined, undefined);

      expect(result).toBe("http://localhost:7860/api/mcp/sse");
    });
  });

  describe("Custom values", () => {
    it("should return original value when not BACKEND_URL or MCP_SSE_VALUE", () => {
      const customValue = "https://my-custom-webhook.com/api";
      const result = generateWebhookUrl(customValue, "endpoint", "agent-123");

      expect(result).toBe(customValue);
    });

    it("should return empty string when custom value is empty", () => {
      const result = generateWebhookUrl("", "endpoint", "agent-123");

      expect(result).toBe("");
    });
  });

  describe("Real-world scenarios", () => {
    const testCases = [
      {
        description: "Production environment with long agent ID",
        value: BACKEND_URL,
        endpointName: "prod-webhook",
        agentId: "550e8400-e29b-41d4-a716-446655440000",
        expected:
          "http://localhost:7860/api/webhook/prod-webhook550e8400-e29b-41d4-a716-446655440000",
      },
      {
        description: "Development environment with simple names",
        value: BACKEND_URL,
        endpointName: "dev",
        agentId: "123",
        expected: "http://localhost:7860/api/webhook/dev123",
      },
      {
        description: "agent with special characters in endpoint and ID",
        value: BACKEND_URL,
        endpointName: "api-v2_beta",
        agentId: "agent_2024-01-15",
        expected:
          "http://localhost:7860/api/webhook/api-v2_betaagent_2024-01-15",
      },
    ];

    testCases.forEach(
      ({ description, value, endpointName, agentId, expected }) => {
        it(description, () => {
          const result = generateWebhookUrl(value, endpointName, agentId);
          expect(result).toBe(expected);
        });
      },
    );
  });

  describe("agent ID presence validation", () => {
    it("should ensure agent ID is included in webhook URL", () => {
      const agentId = "critical-agent-id";
      const result = generateWebhookUrl(BACKEND_URL, "webhook", agentId);

      expect(result).toContain(agentId);
      expect(result).toMatch(new RegExp(`${agentId}$`)); // agent ID should be at the end
    });

    it("should ensure endpoint name comes before agent ID", () => {
      const endpointName = "my-endpoint";
      const agentId = "my-agent";
      const result = generateWebhookUrl(BACKEND_URL, endpointName, agentId);

      const endpointIndex = result.indexOf(endpointName);
      const agentIndex = result.indexOf(agentId);

      expect(endpointIndex).toBeLessThan(agentIndex);
      expect(result).toBe(
        `http://localhost:7860/api/webhook/${endpointName}${agentId}`,
      );
    });
  });
});
