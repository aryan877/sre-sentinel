# 🚀 SRE Sentinel - Complete Setup & Run Guide

## 🎯 System Overview

SRE Sentinel is an AI-powered DevOps copilot that autonomously monitors, diagnoses, and heals infrastructure issues:

- **Detects** anomalies in real-time using Cerebras AI (ultra-fast inference - 2,600 tokens/sec)
- **Diagnoses** root causes using Llama 4 Scout (10M token context for holistic analysis)
- **Heals** issues automatically via Docker MCP Gateway (secure orchestration)
- **Displays** everything in a real-time React dashboard

## 📋 Prerequisites

### Required Software

- **Docker Desktop** (running and accessible)
- **Python 3.11+**
- **Node.js 18+**
- **Git**

### Required API Keys

1. **Cerebras API Key** (free tier available)
   - Get from: https://cloud.cerebras.ai
   - Used for ultra-fast anomaly detection (<1 second)
2. **Llama API Key** (choose one):
   - **OpenRouter** (recommended): https://openrouter.ai
   - **Groq**: https://groq.com
   - Used for deep root cause analysis (3-5 seconds)

---

## 🚀 Quick Start (15 minutes)

### Step 1: Clone and Setup

```bash
# Clone the repository
git clone <your-repo-url>
cd sre-sentinel

# Run the automated setup script
./scripts/setup.sh
```

The setup script will:

- ✅ Check all prerequisites
- ✅ Install Python dependencies
- ✅ Install Node.js dependencies for dashboard and MCP servers
- ✅ Build Docker containers
- ✅ Create `.env` file from template

### Step 2: Configure API Keys

Edit the `.env` file and add your API keys:

```env
# Cerebras API Configuration
CEREBRAS_API_KEY=your_cerebras_key_here
CEREBRAS_MODEL=llama-4-scout-17b-16e-instruct

# Llama 4 Scout Configuration (via OpenRouter)
LLAMA_API_KEY=your_openrouter_key_here
LLAMA_API_BASE=https://openrouter.ai/api/v1
LLAMA_MODEL=meta-llama/llama-4-scout

# Or use Groq instead
# LLAMA_API_KEY=your_groq_key_here
# LLAMA_API_BASE=https://api.groq.com/openai/v1
# LLAMA_MODEL=llama-3.1-70b-versatile

# Other settings (defaults are fine)
API_PORT=8000
AUTO_HEAL_ENABLED=true
```

### Step 3: Start the System

```bash
# Start all Docker containers (includes MCP Gateway)
docker-compose up -d

# Start the dashboard (in a new terminal)
cd dashboard
npm run dev
```

### Step 4: Verify Everything is Working

Open these URLs to verify components:

- **Dashboard**: http://localhost:5173
- **Demo API**: http://localhost:3001/health
- **SRE Sentinel API**: http://localhost:8000/health
- **MCP Gateway**: http://localhost:8811

You should see:

- ✅ Green container status cards in dashboard
- ✅ Real-time metrics charts
- ✅ Live log streaming
- ✅ All health checks passing

---

## 🧪 Testing the System

### Automated Testing (Recommended)

Run the built-in test script:

```bash
./scripts/break-service.sh
```

Choose a failure scenario:

1. **Kill Postgres** - Simulates database crash
2. **Memory leak** - Triggers OOM crash
3. **Remove env var** - Creates configuration error
4. **Max out CPU** - Causes performance issues

### What to Expect

Within 30 seconds, you'll see:

1. **Detection** (Cerebras - <1 second)

   ```
   ⚡ Anomaly detected in 0.8 seconds
   Service: postgres-db
   Confidence: 94%
   ```

2. **Diagnosis** (Llama 4 - 3-5 seconds)

   ```
   🧠 Analyzing 50,000 log lines...
   Root Cause: Postgres crashed due to OOM
   ```

3. **Healing** (MCP Gateway - 10-15 seconds)

   ```
   🔧 Restarting container...
   ✓ System recovered in 12 seconds
   ```

4. **Dashboard Updates**
   - Status changes: 🟢 → 🔴 → 🟡 → 🟢
   - AI insights panel shows explanation
   - Timeline of actions taken

### Manual Testing

#### Test 1: Kill a Container

```bash
# Kill postgres container
docker kill demo-postgres

# Watch SRE Sentinel detect and fix:
# 1. Detects connection errors in API logs
# 2. Analyzes the issue
# 3. Restarts postgres container
```

#### Test 2: Memory Leak

```bash
# Trigger memory leak in demo API
for i in {1..10}; do curl -s http://localhost:3001/leak; done

# Watch container crash and auto-heal
docker stats demo-api
```

#### Test 3: Database Connection Issues

```bash
# Stop postgres
docker stop demo-postgres

# Try database endpoint
curl http://localhost:3001/db-check

# Watch SRE Sentinel restore service
```

---

## 🏗️ System Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Docker        │    │   SRE Sentinel   │    │   Dashboard     │
│   Containers    │───▶│   Core Engine    │───▶│   (React)       │
│                 │    │                  │    │                 │
│ • demo-api      │    │ • Anomaly Detect │    │ • Real-time UI  │
│ • demo-postgres │    │ • Root Cause     │    │ • Metrics       │
│ • mcp-gateway   │    │ • Auto-heal      │    │ • Logs          │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                │
                                ▼
                       ┌──────────────────┐
                       │   AI Services    │
                       │                  │
                       │ • Cerebras       │
                       │ • Llama 4 Scout  │
                       └──────────────────┘
```

### Key Components

1. **Python Monitoring Server** ([`src/monitor.py`](src/monitor.py))

   - Monitors Docker containers with `sre-sentinel.monitor=true` label
   - Streams logs and collects metrics (CPU, memory, network)
   - Detects anomalies and triggers healing
   - Broadcasts events via WebSocket

2. **Cerebras Client** ([`src/cerebras_client.py`](src/cerebras_client.py))

   - Ultra-fast anomaly detection (2,600 tokens/sec)
   - Analyzes 100K log lines in <1 second
   - Returns structured anomaly results with confidence scores

3. **Llama Analyzer** ([`src/llama_analyzer.py`](src/llama_analyzer.py))

   - Deep root cause analysis with 10M token context
   - Analyzes entire system state (logs + configs + code)
   - Generates actionable fix suggestions

4. **MCP Orchestrator** ([`src/mcp_orchestrator.py`](src/mcp_orchestrator.py))

   - Secure execution of fixes via Docker MCP Gateway
   - Isolates and monitors all AI actions
   - Supports container restarts, config updates, resource scaling

5. **React Dashboard** ([`dashboard/`](dashboard/))

   - Real-time WebSocket updates
   - Container status, metrics, logs, and AI insights
   - Beautiful UI with TailwindCSS

6. **MCP Servers** ([`mcp-servers/`](mcp-servers/))
   - **Docker Control** ([`mcp-servers/docker-control/index.js`](mcp-servers/docker-control/index.js)): Container management
   - **Config Patcher** ([`mcp-servers/config-patcher/index.js`](mcp-servers/config-patcher/index.js)): Environment variable updates

---

## 🔧 Configuration Options

### Environment Variables

Edit `.env` to customize behavior:

```env
# AI Model Configuration
CEREBRAS_MODEL=llama-4-scout-17b-16e-instruct
LLAMA_MODEL=meta-llama/llama-4-scout

# Monitoring Settings
LOG_LINES_PER_CHECK=20
LOG_CHECK_INTERVAL=5
API_PORT=8000

# Safety Settings
AUTO_HEAL_ENABLED=true
MANUAL_APPROVAL_MODE=false

# Dashboard
VITE_WS_URL=ws://localhost:8000/ws
VITE_API_URL=http://localhost:8000
```

### Docker Labels

Add these labels to containers you want to monitor:

```yaml
labels:
  - "sre-sentinel.monitor=true"
  - "sre-sentinel.service=your-service-name"
```

---

## 📊 Monitoring and Metrics

The system tracks:

- **Container metrics**: CPU, memory, network usage
- **Log patterns**: Error rates, crash signatures
- **Incident lifecycle**: Detection → Analysis → Healing → Resolution
- **AI performance**: Detection latency, analysis confidence

### Accessing Metrics

- **Dashboard**: Visual charts and real-time updates
- **API endpoints**:
  - `GET /containers` - Current container states
  - `GET /incidents` - Incident history
  - `WebSocket /ws` - Real-time event stream

---

## 🚨 Troubleshooting

### Common Issues

#### Docker containers won't start

```bash
# Check Docker daemon
docker info

# View logs
docker-compose logs

# Rebuild containers
docker-compose down
docker-compose up -d --build
```

#### API key errors

```bash
# Check .env file has keys without quotes
cat .env

# Restart containers
docker-compose restart sre-sentinel

# Check logs
docker-compose logs sre-sentinel
```

#### Dashboard not connecting

1. Check WebSocket connection in browser DevTools
2. Verify `VITE_WS_URL` in dashboard `.env`
3. Check if backend is running: `curl http://localhost:8000/health`

#### MCP servers not responding

```bash
# Check MCP Gateway is running
docker-compose ps mcp-gateway

# Check MCP server installation
cd mcp-servers/docker-control
npm list @modelcontextprotocol/sdk
```

### Health Checks

```bash
# Check all containers
docker-compose ps

# Check individual services
curl http://localhost:3001/health  # Demo API
curl http://localhost:8000/health  # SRE Sentinel
curl http://localhost:8811/health  # MCP Gateway
```

---

## 🔄 Maintenance Commands

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f sre-sentinel

# Dashboard dev server
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

# Monitor resource usage
docker stats
```

---

## 🎯 Success Criteria

Your SRE Sentinel is fully working when:

- ✅ All 4 Docker containers running (MCP Gateway, API, Postgres, SRE Sentinel)
- ✅ Dashboard loads at http://localhost:5173 with green status cards
- ✅ Logs stream in real-time in the dashboard
- ✅ Metrics charts update every few seconds
- ✅ Breaking a service triggers auto-healing within 30 seconds
- ✅ AI insights appear in the dashboard with explanations
- ✅ Services recover automatically without manual intervention

---

## 🎬 Demo Script

For presentations or demos, use this script:

```bash
# 1. Start everything
./scripts/setup.sh
docker-compose up -d
cd dashboard && npm run dev

# 2. Show working system
# Open http://localhost:5173
# Show green status cards, live logs, metrics

# 3. Break something
./scripts/break-service.sh
# Choose option 1 (kill postgres)

# 4. Watch auto-healing
# Explain: Detection → Analysis → Healing → Resolution

# 5. Show results
# Container status returns to green
# AI insights show what happened
```

---

## 📚 Next Steps

Once your system is running:

1. **Add your own containers** to monitor with the `sre-sentinel.monitor=true` label
2. **Customize AI prompts** in [`src/cerebras_client.py`](src/cerebras_client.py) and [`src/llama_analyzer.py`](src/llama_analyzer.py)
3. **Extend MCP servers** in [`mcp-servers/`](mcp-servers/) for custom actions
4. **Configure alerts** by integrating with your notification system

---

## 📋 Startup Checklist

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

## 🔗 Important URLs

- **Dashboard**: http://localhost:5173
- **Demo API**: http://localhost:3001
- **SRE Sentinel API**: http://localhost:8000
- **MCP Gateway**: http://localhost:8811
- **WebSocket**: ws://localhost:8000/ws
- **PostgreSQL**: localhost:5432

---

**🛡️ Happy monitoring! Your infrastructure is now self-healing with AI!**
