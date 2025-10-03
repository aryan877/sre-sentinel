#!/usr/bin/env node

/**
 * MCP Server: Config Patcher
 * Provides tools for updating container configurations
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
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
        description:
          "Update environment variables for a container (requires restart)",
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

        try {
          // Get current config
          const info = await container.inspect();
          const currentEnv = info.Config.Env || [];
          const currentConfig = info.Config;
          const hostConfig = info.HostConfig;
          const name = info.Name;

          // Remove leading slash from container name
          const containerName = name.startsWith("/") ? name.substring(1) : name;

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

          // Stop the container
          await container.stop();

          // Commit the container to create a new image
          const imageRepo = `${containerName}-updated`;
          const imageTag = "latest";
          await container.commit({
            repo: imageRepo,
            tag: imageTag,
            author: "SRE Sentinel",
            message: "Updated environment variables",
            changes: [`ENV ${newEnv.join(" ")}`],
          });

          // Remove the old container
          await container.remove({ force: true });

          // Create a new container with the updated image and environment
          const newContainer = await docker.createContainer({
            Image: `${imageRepo}:${imageTag}`,
            Env: newEnv,
            HostConfig: hostConfig,
            name: containerName,
            // Preserve other configuration from the original container
            ...currentConfig,
            // Override with our updated environment
            Env: newEnv,
          });

          // Start the new container
          await newContainer.start();

          return {
            content: [
              {
                type: "text",
                text: JSON.stringify({
                  success: true,
                  message: `Container ${container_name} recreated with updated environment variables`,
                  updates: env_updates,
                  new_container_id: newContainer.id,
                  new_env: newEnv,
                }),
              },
            ],
          };
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
