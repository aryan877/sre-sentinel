#!/usr/bin/env node

/**
 * MCP Server: Docker Control
 * Provides secure Docker container management tools
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import Docker from "dockerode";

const docker = new Docker();

// Create MCP server
const server = new Server(
  {
    name: "docker-control",
    version: "1.0.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

// Define available tools
server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [
      {
        name: "restart_container",
        description: "Restart a Docker container by name or ID",
        inputSchema: {
          type: "object",
          properties: {
            container_name: {
              type: "string",
              description: "Name or ID of the container to restart",
            },
            reason: {
              type: "string",
              description: "Reason for restarting the container (for audit logs)",
            },
          },
          required: ["container_name"],
        },
      },
      {
        name: "health_check",
        description: "Check the health status of a container",
        inputSchema: {
          type: "object",
          properties: {
            container_name: {
              type: "string",
              description: "Name or ID of the container to check",
            },
          },
          required: ["container_name"],
        },
      },
      {
        name: "update_resources",
        description: "Update CPU and memory limits for a container",
        inputSchema: {
          type: "object",
          properties: {
            container_name: {
              type: "string",
              description: "Name or ID of the container",
            },
            resources: {
              type: "object",
              description: "Resource limits to update (memory, cpu)",
            },
          },
          required: ["container_name", "resources"],
        },
      },
      {
        name: "get_logs",
        description: "Get recent logs from a container",
        inputSchema: {
          type: "object",
          properties: {
            container_name: {
              type: "string",
              description: "Name or ID of the container",
            },
            tail: {
              type: "number",
              description: "Number of lines to retrieve (default: 100)",
            },
          },
          required: ["container_name"],
        },
      },
    ],
  };
});

// Handle tool calls
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  try {
    switch (name) {
      case "restart_container": {
        const { container_name, reason } = args;
        const container = docker.getContainer(container_name);

        await container.restart();

        return {
          content: [
            {
              type: "text",
              text: JSON.stringify({
                success: true,
                message: `Container ${container_name} restarted successfully`,
                reason: reason || "No reason provided",
                timestamp: new Date().toISOString(),
              }),
            },
          ],
        };
      }

      case "health_check": {
        const { container_name } = args;
        const container = docker.getContainer(container_name);
        const info = await container.inspect();

        const status = info.State.Running ? "running" : "stopped";
        const health = info.State.Health?.Status || "none";

        return {
          content: [
            {
              type: "text",
              text: JSON.stringify({
                success: true,
                status: status,
                health: health,
                container: container_name,
                restarts: info.RestartCount,
                started_at: info.State.StartedAt,
              }),
            },
          ],
        };
      }

      case "update_resources": {
        const { container_name, resources } = args;
        const container = docker.getContainer(container_name);

        // Convert resource limits
        const updateConfig = {};
        if (resources.memory) {
          // Convert "512m" to bytes
          const match = resources.memory.match(/^(\d+)([kmg]?)$/i);
          if (match) {
            const [, value, unit] = match;
            const multiplier = { k: 1024, m: 1024 * 1024, g: 1024 * 1024 * 1024 };
            updateConfig.Memory = parseInt(value) * (multiplier[unit?.toLowerCase()] || 1);
          }
        }
        if (resources.cpu) {
          updateConfig.NanoCPUs = parseFloat(resources.cpu) * 1e9;
        }

        await container.update(updateConfig);

        return {
          content: [
            {
              type: "text",
              text: JSON.stringify({
                success: true,
                message: `Resources updated for ${container_name}`,
                updates: updateConfig,
              }),
            },
          ],
        };
      }

      case "get_logs": {
        const { container_name, tail = 100 } = args;
        const container = docker.getContainer(container_name);

        const logs = await container.logs({
          stdout: true,
          stderr: true,
          tail: tail,
        });

        return {
          content: [
            {
              type: "text",
              text: JSON.stringify({
                success: true,
                logs: logs.toString("utf-8"),
                lines: tail,
              }),
            },
          ],
        };
      }

      default:
        throw new Error(`Unknown tool: ${name}`);
    }
  } catch (error) {
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({
            success: false,
            error: error.message,
            tool: name,
          }),
        },
      ],
      isError: true,
    };
  }
});

// Start server
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("Docker Control MCP server running on stdio");
}

main().catch((error) => {
  console.error("Fatal error:", error);
  process.exit(1);
});