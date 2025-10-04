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
              description:
                "Reason for restarting the container (for audit logs)",
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
      {
        name: "exec_command",
        description: "Execute a command inside a running container for diagnostics or remediation",
        inputSchema: {
          type: "object",
          properties: {
            container_name: {
              type: "string",
              description: "Name or ID of the container",
            },
            command: {
              type: "array",
              items: {
                type: "string",
              },
              description: "Command to execute as array (e.g., ['sh', '-c', 'ls /tmp'])",
            },
            timeout: {
              type: "number",
              description: "Command timeout in seconds (default: 30, max: 120)",
            },
          },
          required: ["container_name", "command"],
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

        try {
          // Validate resource inputs
          const validationErrors = [];
          const updateConfig = {};

          if (resources.memory) {
            // Validate memory format
            const match = resources.memory.match(/^(\d+)([kmg]?)$/i);
            if (!match) {
              validationErrors.push(
                `Invalid memory format: ${resources.memory}. Use format like "512m", "1g", etc.`
              );
            } else {
              const [, value, unit] = match;
              const multiplier = {
                k: 1024,
                m: 1024 * 1024,
                g: 1024 * 1024 * 1024,
              };
              const memoryBytes =
                parseInt(value) * (multiplier[unit?.toLowerCase()] || 1);

              // Validate memory limits (minimum 4MB)
              if (memoryBytes < 4 * 1024 * 1024) {
                validationErrors.push(
                  `Memory too low: ${memoryBytes} bytes. Minimum is 4MB.`
                );
              } else {
                updateConfig.Memory = memoryBytes;
              }
            }
          }

          if (resources.cpu) {
            // Validate CPU format
            const cpuValue = parseFloat(resources.cpu);
            if (isNaN(cpuValue) || cpuValue <= 0) {
              validationErrors.push(
                `Invalid CPU value: ${resources.cpu}. Must be a positive number.`
              );
            } else if (cpuValue > 64) {
              // Reasonable upper limit
              validationErrors.push(
                `CPU value too high: ${cpuValue}. Maximum is 64.`
              );
            } else {
              updateConfig.NanoCPUs = cpuValue * 1e9;
            }
          }

          // Return validation errors if any
          if (validationErrors.length > 0) {
            return {
              content: [
                {
                  type: "text",
                  text: JSON.stringify({
                    success: false,
                    message: "Resource validation failed",
                    errors: validationErrors,
                  }),
                },
              ],
              isError: true,
            };
          }

          // Get current container info to compare with new settings
          const containerInfo = await container.inspect();
          const currentMemory = containerInfo.HostConfig.Memory || 0;
          const currentCpu = containerInfo.HostConfig.NanoCPUs || 0;

          // Apply the updates
          await container.update(updateConfig);

          return {
            content: [
              {
                type: "text",
                text: JSON.stringify({
                  success: true,
                  message: `Resources updated for ${container_name}`,
                  updates: updateConfig,
                  previous: {
                    memory: currentMemory,
                    cpu: currentCpu / 1e9,
                  },
                  new: {
                    memory: updateConfig.Memory || currentMemory,
                    cpu: (updateConfig.NanoCPUs || currentCpu) / 1e9,
                  },
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

      case "exec_command": {
        const { container_name, command, timeout = 30 } = args;
        const container = docker.getContainer(container_name);

        try {
          // Validate timeout
          const effectiveTimeout = Math.min(Math.max(timeout, 1), 120);

          // Validate command is array
          if (!Array.isArray(command) || command.length === 0) {
            return {
              content: [
                {
                  type: "text",
                  text: JSON.stringify({
                    success: false,
                    error: "Command must be a non-empty array",
                  }),
                },
              ],
              isError: true,
            };
          }

          // Create exec instance
          const exec = await container.exec({
            Cmd: command,
            AttachStdout: true,
            AttachStderr: true,
          });

          // Start exec with timeout
          const execStream = await exec.start({ Detach: false });

          let output = "";
          let timeoutHandle;
          let completed = false;

          const timeoutPromise = new Promise((_, reject) => {
            timeoutHandle = setTimeout(() => {
              if (!completed) {
                reject(new Error(`Command execution timed out after ${effectiveTimeout}s`));
              }
            }, effectiveTimeout * 1000);
          });

          const streamPromise = new Promise((resolve, reject) => {
            execStream.on("data", (chunk) => {
              output += chunk.toString("utf-8");
            });

            execStream.on("end", () => {
              completed = true;
              clearTimeout(timeoutHandle);
              resolve();
            });

            execStream.on("error", (err) => {
              completed = true;
              clearTimeout(timeoutHandle);
              reject(err);
            });
          });

          await Promise.race([streamPromise, timeoutPromise]);

          // Get exit code
          const inspectData = await exec.inspect();
          const exitCode = inspectData.ExitCode;

          return {
            content: [
              {
                type: "text",
                text: JSON.stringify({
                  success: exitCode === 0,
                  output: output,
                  exit_code: exitCode,
                  command: command.join(" "),
                  container: container_name,
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
