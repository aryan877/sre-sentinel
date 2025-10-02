# 🚀 SRE Sentinel - Complete Setup & Run Guide

---

## Prerequisites

✅ **Required:**

- Docker Desktop (running)
- Python 3.10+
- Node.js 18+
- API Keys:
  - Cerebras API key (get from https://cerebras.ai/)
  - Llama API key (OpenRouter or Groq)

---

## Installation

### Method 1: Automated Setup (Recommended)

```bash
git clone <your-repo-url>
cd sre-sentinel

# Run automated setup
./scripts/setup.sh
```

This will:

- Install Python dependencies
- Install Node.js dependencies for MCP servers and dashboard
- Create `.env` file from template
- Build Docker containers

### Method 2: Manual Setup

```bash
# 1. Clone repo
git clone <your-repo-url>
cd sre-sentinel

# 2. Environment setup
cp .env.example .env
# Edit .env and add your API keys

# 3. Install Python dependencies
cd src
pip install -r requirements.txt
cd ..

# 4. Install MCP server dependencies
cd mcp-servers/docker-control
npm install
cd ../config-patcher
npm install
cd ../..

# 5. Install dashboard dependencies
cd dashboard
npm install
cd ..
```

---

## Configuration

### API Keys

Edit `.env` and add your keys:

```env
# Cerebras API Configuration
CEREBRAS_API_KEY=your_cerebras_key_here
CEREBRAS_MODEL=llama-4-scout-17b-16e-instruct

# Llama 4 Scout Configuration (via OpenRouter or Groq)
LLAMA_API_KEY=your_openrouter_or_groq_key_here
LLAMA_API_BASE=https://openrouter.ai/api/v1
# Alternative: Use Groq
# LLAMA_API_BASE=https://api.groq.com/openai/v1
LLAMA_MODEL=meta-llama/llama-4-scout

# Docker MCP Gateway Configuration
MCP_GATEWAY_URL=http://localhost:8811
MCP_GATEWAY_TRANSPORT=streaming

# SRE Sentinel Configuration
API_PORT=8000
LOG_LEVEL=INFO
AUTO_HEAL_ENABLED=true
MANUAL_APPROVAL_MODE=false
```

---

## Running the System

### Start Everything

```bash
# 1. Start Docker infrastructure (includes MCP Gateway)
docker-compose up -d

# 2. Verify all containers are running
docker-compose ps
```

You should see:

- ✅ `mcp-gateway` (port 8811)
- ✅ `demo-api` (port 3001)
- ✅ `demo-postgres` (port 5432)
- ✅ `sre-sentinel` (port 8000)

```bash
# 3. Start dashboard (in separate terminal)
cd dashboard
npm run dev
```

Open **http://localhost:5173** to see the dashboard.

---

## System Verification

### Health Checks

```bash
# Check Docker containers
docker-compose ps

# Check API health
curl http://localhost:3001/health

# Check SRE Sentinel API
curl http://localhost:8000/health

# Check MCP Gateway
curl http://localhost:8811/health
```

### Expected Outputs

**Demo API** (http://localhost:3001/health):

```json
{
  "status": "healthy",
  "timestamp": "2024-...",
  "service": "demo-api"
}
```

**SRE Sentinel API** (http://localhost:8000/health):

```json
{
  "status": "healthy"
}
```

**Dashboard**: Should show:

- Container status cards (green)
- Real-time metrics charts
- Live log streams
- AI insights panel

---

## Testing the System

### Use the Break Script

```bash
./scripts/break-service.sh
```

Choose a failure scenario:

1. **Kill Postgres** - Simulates database crash (connection failures)
2. **Memory leak** - Triggers OOM crash
3. **Remove env var** - Creates configuration error
4. **Max out CPU** - Causes performance issues

### Watch SRE Sentinel Work

You'll see (in ~30 seconds):

1. **Detection** (Cerebras)

   ```
   ⚡ Anomaly detected in 0.8 seconds
   Service: postgres-db
   Confidence: 94%
   ```

2. **Diagnosis** (Llama 4)

   ```
   🧠 Analyzing 50,000 log lines...
   Root Cause: Postgres crashed (OOM)
   ```

3. **Healing** (MCP Gateway)

   ```
   🔧 Restarting container...
   ✓ System recovered in 12 seconds
   ```

4. **Dashboard Updates**
   - Status changes: 🟢 → 🔴 → 🟡 → 🟢
   - AI insights panel shows explanation
   - Timeline of actions taken

### Manual Testing

**Test 1: Kill a container**

```bash
docker kill demo-postgres

# Watch SRE Sentinel detect and fix:
# 1. Detects connection errors in API logs
# 2. Analyzes the issue
# 3. Restarts postgres container
```

**Test 2: Memory leak**

```bash
# Trigger memory leak
for i in {1..10}; do curl http://localhost:3001/leak; done

# Watch container crash and auto-heal
docker stats demo-api
```

**Test 3: Database check**

```bash
# Stop postgres
docker stop demo-postgres

# Try database endpoint
curl http://localhost:3001/db-check

# Watch SRE Sentinel restore service
```

---

## Component Details

### Python Monitoring Server

**Location**: `src/monitor.py`

**What it does**:

- Monitors Docker containers with label `sre-sentinel.monitor=true`
- Streams logs and collects metrics (CPU, memory, network)
- Detects anomalies using Cerebras AI
- Generates fix suggestions using Llama 4
- Executes fixes via MCP servers
- Broadcasts events via WebSocket

**Key files**:

- `src/monitor.py` - Main orchestrator
- `src/cerebras_client.py` - Anomaly detection
- `src/llama_analyzer.py` - Root cause analysis
- `src/mcp_orchestrator.py` - Fix execution
- `src/websocket_server.py` - Dashboard API
- `src/event_bus.py` - Event broadcasting

### MCP Servers

**Location**: `mcp-servers/`

The MCP Gateway (port 8811) manages two custom MCP servers:

**Docker Control Server** (`mcp-servers/docker-control/`):

- `restart_container` - Restart containers
- `health_check` - Check container health
- `update_resources` - Modify CPU/memory limits
- `get_logs` - Fetch container logs

**Config Patcher Server** (`mcp-servers/config-patcher/`):

- `update_env_vars` - Patch environment variables

Both servers are automatically started by the MCP Gateway container and use stdio transport for communication.

### React Dashboard

**Features**:

- Real-time container status cards
- Live metrics charts (CPU, memory, network)
- Streaming log viewer with syntax highlighting
- AI insights panel showing incidents and fixes

**Development**:

```bash
cd dashboard
npm run dev    # Start dev server on port 5173
npm run build  # Build for production
npm run lint   # Run ESLint
```

---

## Troubleshooting

### Docker containers won't start

**Solution**:

```bash
# Check Docker daemon
docker info

# View logs
docker-compose logs

# Rebuild containers
docker-compose down
docker-compose up -d --build
```

### SRE Sentinel can't detect containers

**Check labels**:

```bash
# Inspect container labels
docker inspect demo-api | grep -A 5 Labels

# Should see:
# "sre-sentinel.monitor": "true"
# "sre-sentinel.service": "api"
```

### Dashboard not connecting

**Check WebSocket**:

1. Open browser DevTools → Network → WS
2. Should see connection to `ws://localhost:8000/ws`
3. Check dashboard `.env` for correct `VITE_WS_URL`

**Verify backend**:

```bash
curl http://localhost:8000/health
```

### Python import errors

**Solution**:

```bash
# Ensure virtual environment is activated
source venv/bin/activate

# Reinstall dependencies
cd src
pip install -r requirements.txt
```

### MCP servers not responding

**Check installation**:

```bash
cd mcp-servers/docker-control
npm list @modelcontextprotocol/sdk

# Should show version 1.0.0 or higher
```

### API keys not working

**Verify keys**:

1. Check `.env` file has keys without quotes
2. Restart containers: `docker-compose restart sre-sentinel`
3. Check logs: `docker-compose logs sre-sentinel`

### MCP Gateway not found

**Install Docker MCP plugin**:

```bash
# Download from GitHub releases
# https://github.com/docker/mcp-gateway/releases

# Copy to plugins directory
cp docker-mcp ~/.docker/cli-plugins/
chmod +x ~/.docker/cli-plugins/docker-mcp
```

---

## Startup Checklist

- [ ] Docker Desktop is running
- [ ] `.env` file exists with valid API keys
- [ ] Python dependencies installed
- [ ] MCP server dependencies installed
- [ ] Dashboard dependencies installed
- [ ] Docker containers running (`docker-compose up -d`)
- [ ] All containers are healthy (`docker-compose ps`)
- [ ] Dashboard running (`npm run dev` in dashboard)
- [ ] Can access http://localhost:5173
- [ ] Can access http://localhost:3001/health
- [ ] Can access http://localhost:8000/health

---

## Important URLs

- **Dashboard**: http://localhost:5173
- **Demo API**: http://localhost:3001
- **SRE Sentinel API**: http://localhost:8000
- **MCP Gateway**: http://localhost:8811
- **WebSocket**: ws://localhost:8000/ws
- **PostgreSQL**: localhost:5432

---

## Maintenance Commands

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f sre-sentinel

# Dashboard dev server logs
cd dashboard && npm run dev
```

### Restart Services

```bash
# Restart all
docker-compose restart

# Restart specific service
docker-compose restart sre-sentinel

# Clean restart
docker-compose down
docker-compose up -d --build
```

### Monitor Resources

```bash
# Watch all containers
watch docker-compose ps

# Monitor resources
docker stats
```

---

## Success Criteria

System is working correctly when:

- ✅ All 4 Docker containers running (MCP Gateway, API, Postgres, SRE Sentinel)
- ✅ Dashboard loads and shows green status cards
- ✅ Logs stream in real-time
- ✅ Metrics charts update every few seconds
- ✅ Breaking a service triggers auto-healing
- ✅ AI insights appear in the dashboard
- ✅ Services recover automatically

---

**Happy Monitoring! 🛡️**
