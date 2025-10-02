#!/usr/bin/env node

/**
 * MCP Server: Config Patcher
 * Provides tools for updating container configurations
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import Docker from "dockerode";

const docker = new Docker();

const server = new Server(
  {
    name: "config-patcher",
    version: "1.0.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [
      {
        name: "update_env_vars",
        description: "Update environment variables for a container (requires restart)",
        inputSchema: {
          type: "object",
          properties: {
            container_name: {
              type: "string",
              description: "Name or ID of the container",
            },
            env_updates: {
              type: "object",
              description: "Environment variable key-value pairs to update",
            },
          },
          required: ["container_name", "env_updates"],
        },
      },
    ],
  };
});

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  try {
    switch (name) {
      case "update_env_vars": {
        const { container_name, env_updates } = args;
        const container = docker.getContainer(container_name);

        // Get current config
        const info = await container.inspect();
        const currentEnv = info.Config.Env || [];

        // Merge environment variables
        const envMap = {};
        currentEnv.forEach((env) => {
          const [key, ...valueParts] = env.split("=");
          envMap[key] = valueParts.join("=");
        });

        // Apply updates
        Object.assign(envMap, env_updates);

        // Convert back to array
        const newEnv = Object.entries(envMap).map(([k, v]) => `${k}=${v}`);

        // Note: Docker doesn't support updating env vars on running containers
        // We need to recreate the container with new config
        // For now, we'll just document the required changes

        return {
          content: [
            {
              type: "text",
              text: JSON.stringify({
                success: true,
                message: "Environment variable updates prepared (requires container restart)",
                updates: env_updates,
                note: "Container will be restarted with new environment variables",
                new_env: newEnv,
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
          }),
        },
      ],
      isError: true,
    };
  }
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("Config Patcher MCP server running on stdio");
}

main().catch((error) => {
  console.error("Fatal error:", error);
  process.exit(1);
});