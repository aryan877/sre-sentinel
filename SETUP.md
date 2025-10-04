# SRE Sentinel Setup Guide

This guide will help you set up and configure SRE Sentinel for monitoring and self-healing your containerized applications.

## Prerequisites

- Docker and Docker Compose (latest versions)
- Python 3.9+
- Node.js 16+ (for MCP servers)
- Redis 6+ (for event bus)
- API keys for Cerebras and Llama AI services

## 1. Clone the Repository

```bash
git clone https://github.com/your-org/sre-sentinel.git
cd sre-sentinel
```

## 2. Configure Environment Variables

Copy the example environment file and configure it with your settings:

```bash
cp .env-example .env
```

Edit `.env` with the following variables:

```bash
# AI Service API Keys
CEREBRAS_API_KEY=your_cerebras_api_key_here
LLAMA_API_KEY=your_llama_api_key_here
LLAMA_API_BASE=https://openrouter.ai/api/v1  # Optional, uses OpenRouter by default

# System Configuration
MCP_GATEWAY_URL=http://mcp-gateway:8811  # URL of the MCP Gateway
API_PORT=8000  # Port for the API server
API_HOST=0.0.0.0  # Host for the API server
AUTO_HEAL_ENABLED=true  # Enable/disable automatic healing

# Redis Configuration
REDIS_HOST=redis  # Redis server host
REDIS_PORT=6379  # Redis server port
REDIS_PASSWORD=  # Redis password (if required)
REDIS_DB=0  # Redis database number

# Log Analysis Configuration
LOG_LINES_PER_CHECK=20  # Number of log lines to analyze at once
LOG_CHECK_INTERVAL=5.0  # Interval between log checks (seconds)
```

## 3. Start the System

Use Docker Compose to start all components:

```bash
docker-compose up -d
```

This will start:

- Demo API service (Node.js)
- PostgreSQL database
- Redis for event bus
- MCP Gateway with Docker control tools
- SRE Sentinel monitoring agent

## 4. Verify the Setup

### Check Container Status

```bash
docker-compose ps
```

All containers should be in a "running" state.

### Check the Dashboard

Open http://localhost:8000 in your browser to access the monitoring dashboard.

### Check MCP Gateway Health

```bash
curl http://localhost:8811/health
```

You should see a healthy response from the MCP Gateway.

## 5. Configure Monitoring

### Add Monitoring Labels to Containers

Add these labels to containers you want to monitor in your `docker-compose.yml`:

```yaml
labels:
  - "sre-sentinel.monitor=true"
  - "sre-sentinel.service=your-service-name"
```

### Example Configuration

```yaml
version: "3.8"
services:
  your-service:
    image: your-image
    labels:
      - "sre-sentinel.monitor=true"
      - "sre-sentinel.service=your-service"
    # Your other configuration...
```

## 6. Test the System

### Trigger a Test Incident

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

### Verify Incident Handling

1. Check the dashboard for the incident
2. Review the AI analysis and recommended fixes
3. Verify that the service was automatically restored

## 7. MCP Configuration

### Understanding MCP Servers

SRE Sentinel uses two MCP servers for container management:

1. **Docker Control Server** (`mcp-servers/docker-control/`)

   - Provides tools for container management
   - Handles restarts, health checks, resource updates, and log retrieval

2. **Config Patcher Server** (`mcp-servers/config-patcher/`)
   - Provides tools for configuration updates
   - Handles environment variable updates

### Adding Custom MCP Servers

1. Create a new MCP server in `mcp-servers/your-server/`
2. Implement your tools following the MCP specification
3. Add the server definition to `mcp-servers/catalog.yaml` (follow the existing entries for structure and metadata).

4. Rebuild the MCP server images so the gateway can start the new server:

```bash
./mcp-servers/build-servers.sh
```

5. Restart the MCP Gateway:

```bash
docker-compose restart mcp-gateway
```

## 8. Customization

### Custom AI Analysis

Modify the AI analysis in:

- `src/cerebras_client.py`: Anomaly detection logic
- `src/llama_analyzer.py`: Root cause analysis logic

### Custom Monitoring

Extend monitoring in `src/monitor.py`:

- Add new metrics collection
- Implement custom anomaly detection
- Add specialized fix actions

### Custom Dashboard

Modify the dashboard in `dashboard/`:

- Update the UI components
- Add new visualizations
- Customize the event handling

## 9. Troubleshooting

### Common Issues

1. **MCP Gateway Connection Issues**

   - Check if the MCP Gateway is running: `docker-compose ps mcp-gateway`
   - Check MCP Gateway logs: `docker-compose logs mcp-gateway`
   - Verify the MCP Gateway URL in your environment variables

2. **AI Service Connection Issues**

   - Verify your API keys are correct
   - Check if the AI services are accessible from your network
   - Review the AI service logs for error messages

3. **Redis Connection Issues**

   - Check if Redis is running: `docker-compose ps redis`
   - Verify Redis connection parameters in your environment variables
   - Check Redis logs: `docker-compose logs redis`

4. **Container Monitoring Issues**
   - Verify containers have the correct labels
   - Check if the SRE Sentinel can access Docker socket
   - Review the SRE Sentinel logs: `docker-compose logs sre-sentinel`

### Debug Mode

Enable debug mode for more detailed logging:

```bash
# Set log level to debug
LOG_LEVEL=debug docker-compose up
```

### Manual MCP Testing

Test MCP tools directly:

```bash
# List available tools
curl -X POST http://localhost:8811/mcp/list_tools

# Test container restart
curl -X POST http://localhost:8811/mcp/call \
  -H "Content-Type: application/json" \
  -d '{"name": "restart_container", "arguments": {"container_name": "demo-api", "reason": "Manual test"}}'

# Test health check
curl -X POST http://localhost:8811/mcp/call \
  -H "Content-Type: application/json" \
  -d '{"name": "health_check", "arguments": {"container_name": "demo-api"}}'
```

## 10. Production Deployment

### Security Considerations

1. **API Keys**: Store API keys securely using a secrets management system
2. **Network Security**: Configure firewall rules to restrict access
3. **Container Security**: Run containers with non-root users
4. **Resource Limits**: Set appropriate resource limits for containers

### Scaling Considerations

1. **Redis**: Use a managed Redis service for production
2. **Monitoring**: Set up external monitoring for the SRE Sentinel itself
3. **Logging**: Configure centralized logging for all components
4. **Backup**: Regularly back up configuration and data

### High Availability

1. **Redundancy**: Deploy multiple instances of critical components
2. **Load Balancing**: Use a load balancer for the API server
3. **Failover**: Configure automatic failover for critical services
4. **Health Checks**: Set up comprehensive health checks

## 11. Maintenance

### Regular Tasks

1. **Update Dependencies**: Regularly update Docker images and dependencies
2. **Review Logs**: Periodically review logs for issues or optimizations
3. **Monitor Performance**: Track system performance and resource usage
4. **Backup Configuration**: Regularly back up configuration files

### Upgrading SRE Sentinel

1. **Backup**: Back up your configuration and data
2. **Update**: Pull the latest version of SRE Sentinel
3. **Migrate**: Follow any migration instructions for the new version
4. **Test**: Thoroughly test the new version before deploying to production

## 12. Support

For support and questions:

1. **Documentation**: Check the [README.md](README.md) for detailed information
2. **Issues**: Report issues on the GitHub repository
3. **Community**: Join our community forum for discussions
4. **Support**: Contact our support team for enterprise support
