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

SRE Sentinel uses the Model Context Protocol (MCP) to securely interact with container infrastructure:

### MCP Servers

1. **Docker Control Server** (`mcp-servers/docker-control/`)

   - `restart_container`: Restart a Docker container
   - `health_check`: Check container health status
   - `update_resources`: Update CPU and memory limits
   - `get_logs`: Retrieve recent container logs
   - `exec_command`: Execute commands inside containers for diagnostics or remediation

2. **Config Patcher Server** (`mcp-servers/config-patcher/`)
   - `update_env_vars`: Update environment variables for containers

### Dynamic Tool Discovery

The MCP orchestrator automatically discovers available tools from the MCP gateway at runtime, eliminating the need for hardcoding tool definitions. This allows for:

- Automatic tool discovery from MCP servers
- Dynamic parameter validation based on tool schemas
- Flexible tool execution with proper error handling
- Easy addition of new MCP servers and tools

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

Test MCP tools directly:

```bash
# Test container restart
curl -X POST http://localhost:8811/mcp/call \
  -H "Content-Type: application/json" \
  -d '{"name": "restart_container", "arguments": {"container_name": "demo-api", "reason": "Manual test"}}'

# Test health check
curl -X POST http://localhost:8811/mcp/call \
  -H "Content-Type: application/json" \
  -d '{"name": "health_check", "arguments": {"container_name": "demo-api"}}'
```

## 🛡️ Security

- MCP Gateway provides secure isolation between AI and container infrastructure
- All tool executions are logged and auditable
- Container access is limited to specific operations
- Sensitive environment variables are redacted in AI prompts

## 📈 Extending SRE Sentinel

### Adding New MCP Servers

1. Create a new MCP server in `mcp-servers/your-server/`
2. Implement your tools following the MCP specification
3. Add the server definition to `mcp-servers/catalog.yaml`
4. Rebuild the MCP server images:

   ```bash
   ./mcp-servers/build-servers.sh
   ```

5. Restart the MCP Gateway to load the new server:

   ```bash
   docker-compose restart mcp-gateway
   ```

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
