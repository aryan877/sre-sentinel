# SRE Sentinel - AI DevOps Copilot

SRE Sentinel is an AI-powered monitoring and self-healing system for containerized applications. It continuously monitors Docker containers, detects anomalies using advanced AI analysis, performs root cause analysis, and executes automated fixes through the Model Context Protocol (MCP).

## 🚀 Features

- **Real-time Monitoring**: Continuously monitors Docker containers for logs, metrics, and events
- **AI-Powered Anomaly Detection**: Uses Cerebras AI for fast anomaly detection in container logs
- **Deep Root Cause Analysis**: Leverages Llama 4 Scout for comprehensive incident analysis
- **Automated Remediation**: Executes fixes through secure MCP Gateway with Docker control tools
- **Dynamic Tool Discovery**: Automatically discovers available tools from MCP servers
- **Real-time Telemetry**: Provides WebSocket-based real-time event streaming
- **Human-Friendly Explanations**: Generates stakeholder-friendly incident explanations

## 🏗️ Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Containers    │───▶│   SRE Sentinel  │───▶│   Event Bus     │
│                 │    │                 │    │                 │
│ - Logs          │    │ - Monitor       │    │ - Publish       │
│ - Metrics       │    │ - Detect        │    │ - Persist       │
│ - Events        │    │ - Analyze       │    │ - Distribute    │
└─────────────────┘    │ - Remediate     │    └─────────────────┘
                       └─────────────────┘
                                 │
                                 ▼
                        ┌─────────────────┐
                        │   AI Services   │
                        │                 │
                        │ - Cerebras      │
                        │ - Llama         │
                        └─────────────────┘
                                 │
                                 ▼
                        ┌─────────────────┐
                        │   MCP Gateway   │
                        │                 │
                        │ - Docker Control│
                        │ - Config Patcher│
                        └─────────────────┘
```

## 🛠️ MCP Integration

SRE Sentinel uses the Model Context Protocol (MCP) to securely interact with container infrastructure through the Docker MCP Gateway. This architecture provides a secure, audited, and extensible way to execute container operations.

### MCP Architecture Overview

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   SRE Sentinel  │───▶│  MCP Gateway    │───▶│  MCP Servers    │
│   (Python)      │    │  (Docker)       │    │  (Node.js)      │
│                 │    │                 │    │                 │
│ - AI Analysis   │    │ - Session Mgmt  │    │ - Docker API    │
│ - Fix Actions   │    │ - Tool Routing  │    │ - Config Mgmt   │
│ - SSE Client    │    │ - Security      │    │ - Validation    │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### MCP Gateway Connection

The Python orchestrator connects to the MCP Gateway using Server-Sent Events (SSE) protocol:

1. **Session Initialization**: Establishes a session with the MCP Gateway
2. **Tool Discovery**: Automatically discovers available tools from all registered MCP servers
3. **Dynamic Execution**: Executes tools with proper parameter validation and error handling
4. **Security Isolation**: All container operations go through the Gateway's security layer

### MCP Servers

#### 1. Docker Control Server (`mcp-servers/docker-control/`)

Provides secure Docker container management tools:

- **`restart_container`**: Restart a Docker container

  - Parameters: `container_name` (required), `reason` (optional)
  - Example: `{"container_name": "demo-api", "reason": "Memory leak detected"}`

- **`health_check`**: Check container health status

  - Parameters: `container_name` (required)
  - Returns: Status, health state, restart count, start time

- **`update_resources`**: Update CPU and memory limits

  - Parameters: `container_name` (required), `resources` (required)
  - Example: `{"container_name": "demo-api", "resources": {"memory": "1g", "cpu": "1.0"}}`

- **`get_logs`**: Retrieve recent container logs

  - Parameters: `container_name` (required), `tail` (optional, default: 100)
  - Returns: Last N lines of container logs

- **`exec_command`**: Execute commands inside containers
  - Parameters: `container_name` (required), `command` (required, array), `timeout` (optional)
  - Example: `{"container_name": "demo-api", "command": ["sh", "-c", "ps aux"], "timeout": 30}`

#### 2. Config Patcher Server (`mcp-servers/config-patcher/`)

Handles configuration updates for containers:

- **`update_env_vars`**: Update environment variables
  - Parameters: `container_name` (required), `env_updates` (required)
  - Process: Commits container as image, recreates with new environment
  - Example: `{"container_name": "demo-api", "env_updates": {"DEBUG": "true", "LOG_LEVEL": "info"}}`

### Dynamic Tool Discovery

The MCP orchestrator (`src/core/orchestrator.py`) automatically discovers available tools:

```python
# Tools are discovered at runtime from the MCP Gateway
async def _discover_tools(self) -> None:
    # Connects to MCP Gateway via SSE
    # Retrieves tool schemas and descriptions
    # Builds dynamic tool registry
```

This approach provides:

- **Automatic Discovery**: No hardcoded tool definitions
- **Schema Validation**: Dynamic parameter validation based on tool schemas
- **Flexible Execution**: Proper error handling and response parsing
- **Easy Extension**: Add new MCP servers without code changes

### MCP Tool Execution Flow

1. **AI Analysis**: Llama AI analyzes incidents and recommends `FixAction` objects
2. **Tool Mapping**: `FixAction.action` maps to MCP tool names
3. **Parameter Preparation**: `FixAction.details` contains JSON parameters for the tool
4. **Gateway Execution**: Tool call is sent to MCP Gateway via SSE
5. **Result Processing**: Response is parsed and returned as `FixExecutionResult`

### Security Features

- **Isolation**: AI never directly accesses Docker socket
- **Audit Trail**: All tool executions are logged in the Gateway
- **Parameter Validation**: Strict schema validation prevents injection
- **Session Management**: Secure session-based communication
- **Limited Scope**: Each tool has specific, limited capabilities

### Adding New MCP Servers

1. Create server in `mcp-servers/your-server/`
2. Implement tools following MCP specification
3. Add to `mcp-servers/catalog.yaml`:
   ```yaml
   your-server:
     description: "Your server description"
     image: "mcp-servers/your-server:latest"
     tools:
       - name: "your_tool"
         description: "What your tool does"
     volumes:
       - "/var/run/docker.sock:/var/run/docker.sock"
   ```
4. Build and restart:
   ```bash
   ./mcp-servers/build-servers.sh
   docker-compose restart mcp-gateway
   ```

## 📋 Prerequisites

- Docker and Docker Compose
- Python 3.9+
- Node.js (for MCP servers)
- Redis (for event bus)
- API keys for Cerebras and Llama AI services

## 🚀 Quick Start

1. **Clone the repository**:

   ```bash
   git clone https://github.com/your-org/sre-sentinel.git
   cd sre-sentinel
   ```

2. **Set up environment variables**:

   ```bash
   cp .env-example .env
   # Edit .env with your API keys and configuration
   ```

3. **Run the project setup** (installs deps and builds MCP images):

   ```bash
   ./scripts/setup.sh
   ```

4. **Start the system**:

   ```bash
   docker-compose up -d
   ```

5. **View the dashboard**:
   Open http://localhost:3000 in your browser

## 🔧 Configuration

### Environment Variables

- `CEREBRAS_API_KEY`: API key for Cerebras AI service
- `LLAMA_API_KEY`: API key for Llama AI service
- `LLAMA_API_BASE`: Base URL for Llama API (default: https://openrouter.ai/api/v1)
- `MCP_GATEWAY_URL`: URL of the MCP Gateway (default: http://mcp-gateway:8811)
- `API_PORT`: Port for the API server (default: 8000)
- `AUTO_HEAL_ENABLED`: Enable automatic healing (default: true)
- `REDIS_HOST`: Redis server host (default: redis)
- `REDIS_PORT`: Redis server port (default: 6379)

### Docker Compose Labels

Add these labels to containers you want to monitor:

```yaml
labels:
  - "sre-sentinel.monitor=true"
  - "sre-sentinel.service=your-service-name"
```

## 📊 Monitoring Dashboard

The web dashboard provides real-time visibility into:

- Container status and resource usage
- Log streaming with anomaly highlighting
- Incident history and analysis results
- AI insights and recommendations

## 🔍 How It Works

1. **Monitoring**: SRE Sentinel continuously monitors labeled containers
2. **Anomaly Detection**: Cerebras AI analyzes log patterns for anomalies
3. **Incident Creation**: Critical anomalies trigger incident creation
4. **Root Cause Analysis**: Llama 4 Scout performs deep analysis
5. **Fix Execution**: Recommended fixes are executed via MCP Gateway
6. **Health Verification**: Container health is verified after fixes
7. **Resolution**: Incidents are marked resolved with explanations

## 🧪 Testing

### Break a Service

Use the provided script to simulate a service failure:

```bash
./scripts/break-service.sh
```

This will:

- Stop the demo API service
- Trigger anomaly detection
- Create an incident
- Execute automated fixes
- Restore service health

### Manual MCP Testing

Test MCP tools directly through the Gateway:

```bash
# First, initialize a session
curl -X POST http://localhost:8811/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2024-11-05",
      "capabilities": {},
      "clientInfo": {"name": "test-client", "version": "1.0.0"}
    }
  }'

# Then list available tools (using session ID from response)
curl -X POST http://localhost:8811/mcp \
  -H "Content-Type: application/json" \
  -H "Mcp-Session-Id: YOUR_SESSION_ID" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list",
    "params": {}
  }'

# Test container restart
curl -X POST http://localhost:8811/mcp \
  -H "Content-Type: application/json" \
  -H "Mcp-Session-Id: YOUR_SESSION_ID" \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "restart_container",
      "arguments": {"container_name": "demo-api", "reason": "Manual test"}
    }
  }'
```

### MCP Configuration

The MCP Gateway is configured in `docker-compose.yml`:

```yaml
mcp-gateway:
  image: docker/mcp-gateway:latest
  command:
    - --transport=streaming # Enable SSE for Python client
    - --port=8811
    - --catalog=/mcp-servers/catalog.yaml
    - --enable-all-servers
    - --verbose
    - --log-calls
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock # Docker access
    - ./mcp-servers:/mcp-servers:ro # Server definitions
```

### Python MCP Client Implementation

The SRE Sentinel Python client implements the MCP protocol:

1. **Session Management** (`src/core/orchestrator.py`):

   ```python
   async def _initialize_session(self, url: str) -> None:
       # Initialize MCP session with Gateway
       # Extract session ID from response headers
       # Use session ID for subsequent requests
   ```

2. **Tool Discovery**:

   ```python
   async def _discover_tools(self) -> None:
       # List all available tools from Gateway
       # Parse tool schemas and descriptions
       # Build dynamic tool registry
   ```

3. **Tool Execution**:
   ```python
   async def _call_tool(self, tool_name: str, args: dict) -> FixExecutionResult:
       # Execute tool via MCP Gateway
       # Handle SSE response format
       # Parse and return results
   ```

### MCP Message Flow

```
1. Python Client (SRE Sentinel)
   ↓ JSON-RPC 2.0 via SSE
2. MCP Gateway (Docker)
   ↓ Routes to appropriate server
3. MCP Server (Node.js)
   ↓ Executes Docker operation
4. Returns result through Gateway
   ↓ SSE response
5. Python Client receives result
```

## 🛡️ Security

- MCP Gateway provides secure isolation between AI and container infrastructure
- All tool executions are logged and auditable
- Container access is limited to specific operations
- Sensitive environment variables are redacted in AI prompts

## 📈 Extending SRE Sentinel

### MCP Server Development

#### Creating a New MCP Server

1. **Create Server Directory**:

   ```bash
   mkdir mcp-servers/your-server
   cd mcp-servers/your-server
   ```

2. **Initialize Node.js Project**:

   ```bash
   npm init -y
   npm install @modelcontextprotocol/sdk dockerode
   ```

3. **Implement Server** (`index.js`):

   ```javascript
   import { Server } from "@modelcontextprotocol/sdk/server/index.js";
   import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

   const server = new Server(
     {
       name: "your-server",
       version: "1.0.0",
     },
     {
       capabilities: { tools: {} },
     }
   );

   // Define tools
   server.setRequestHandler(ListToolsRequestSchema, async () => ({
     tools: [
       {
         name: "your_tool",
         description: "What your tool does",
         inputSchema: {
           type: "object",
           properties: {
             param1: { type: "string", description: "Parameter description" },
           },
           required: ["param1"],
         },
       },
     ],
   }));

   // Handle tool calls
   server.setRequestHandler(CallToolRequestSchema, async (request) => {
     const { name, arguments: args } = request.params;
     // Implement your tool logic here
     return {
       content: [{ type: "text", text: JSON.stringify(result) }],
     };
   });

   // Start server
   const transport = new StdioServerTransport();
   await server.connect(transport);
   ```

4. **Add to Catalog** (`mcp-servers/catalog.yaml`):

   ```yaml
   your-server:
     description: "Your custom MCP server"
     title: "Your Server"
     type: "server"
     dateAdded: "2025-10-05T00:00:00Z"
     image: "mcp-servers/your-server:latest"
     tools:
       - name: "your_tool"
         description: "What your tool does"
     env:
       - name: "NODE_ENV"
         value: "production"
     volumes:
       - "/var/run/docker.sock:/var/run/docker.sock"
     metadata:
       category: "custom"
       tags: ["your", "tags"]
       license: "MIT License"
       owner: "Your Name"
   ```

5. **Build and Deploy**:

   ```bash
   # Build all MCP servers
   ./mcp-servers/build-servers.sh

   # Restart Gateway to load new server
   docker-compose restart mcp-gateway
   ```

#### Best Practices for MCP Servers

- **Validation**: Always validate input parameters
- **Error Handling**: Return structured error responses
- **Security**: Never expose sensitive data in tool responses
- **Logging**: Use stderr for logging (MCP standard)
- **Idempotency**: Design tools to be idempotent where possible

### Custom AI Analysis

Modify the AI analysis in:

- `src/cerebras_client.py`: Anomaly detection logic
- `src/llama_analyzer.py`: Root cause analysis logic

### Custom Monitoring

Extend monitoring in `src/monitor.py`:

- Add new metrics collection
- Implement custom anomaly detection
- Add specialized fix actions

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [Model Context Protocol](https://modelcontextprotocol.io/) for secure AI-tool integration
- [Cerebras](https://cerebras.ai/) for fast AI inference
- [Llama](https://llama.meta.com/) for advanced reasoning capabilities
- [Docker](https://www.docker.com/) for containerization platform
