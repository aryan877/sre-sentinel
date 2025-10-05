# SRE Sentinel - Professional Code Structure

This directory contains the SRE Sentinel monitoring and self-healing system organized into a professional, modular structure.

## Directory Structure

```
src/
├── __init__.py              # Package initialization
├── main.py                  # Main entry point (runs the whole show)
├── requirements.txt         # Python dependencies
├── README.md               # This file
│
├── models/                  # Data models and schemas
│   ├── __init__.py
│   └── sentinel_types.py   # All Pydantic models, enums, and types
│
├── core/                   # Core monitoring and orchestration
│   ├── __init__.py
│   ├── monitor.py          # Main SRE Sentinel monitoring engine
│   └── orchestrator.py     # MCP Gateway orchestrator for fix execution
│
├── ai/                     # AI-powered analysis components
│   ├── __init__.py
│   ├── cerebras_client.py  # Fast anomaly detection using Cerebras
│   ├── llama_analyzer.py   # Deep root cause analysis with Llama 4
│   └── openrouter_client.py # OpenAI client factory for AI models
│
├── infrastructure/         # Infrastructure and messaging
│   ├── __init__.py
│   └── redis_event_bus.py  # Redis-based event bus for real-time messaging
│
├── api/                    # Web API and dashboard endpoints
│   ├── __init__.py
│   └── websocket_server.py # FastAPI app with WebSocket and REST endpoints
│
└── utils/                  # Utility functions and helpers
    ├── __init__.py
    └── api_key_detector.py # Security utilities for detecting sensitive data
```

## Component Overview

### Main Entry Point

- **`main.py`** - The primary entry point that orchestrates all components and starts both the monitoring loop and API server

### Core Components

- **`core/monitor.py`** - Contains the `SRESentinel` class that runs the main monitoring loop, tracks container states, and manages incidents
- **`core/orchestrator.py`** - Contains the `MCPOrchestrator` class that executes automated fixes via the MCP Gateway

### AI Components

- **`ai/cerebras_client.py`** - Fast anomaly detection using Cerebras AI model
- **`ai/llama_analyzer.py`** - Deep root cause analysis using Llama 4 Scout's long context
- **`ai/openrouter_client.py`** - OpenAI-compatible client factory for accessing AI models

### Infrastructure

- **`infrastructure/redis_event_bus.py`** - Redis-based pub/sub system for real-time event streaming between components

### API Layer

- **`api/websocket_server.py`** - FastAPI application providing REST endpoints and WebSocket connections for the dashboard

### Utilities

- **`utils/api_key_detector.py`** - Security utilities for detecting and redacting sensitive information

### Shared Types

- **`sentinel_types.py`** - All Pydantic models, enums, and type definitions shared across components

## How It Works

1. **`main.py`** starts the application by:

   - Initializing the Redis event bus
   - Creating the SRE Sentinel monitoring engine
   - Building the FastAPI application
   - Starting both the monitoring loop and API server concurrently

2. **`core/monitor.py`** continuously:

   - Monitors Docker containers for logs and metrics
   - Detects anomalies using AI analysis
   - Manages incident lifecycle
   - Publishes real-time events

3. **AI components** provide:

   - Fast anomaly detection (Cerebras)
   - Deep root cause analysis (Llama)
   - Intelligent fix recommendations

4. **`core/orchestrator.py`** executes:

   - Automated fixes via MCP Gateway
   - Health verification after fixes
   - Tool discovery and management

5. **`api/websocket_server.py`** serves:
   - REST endpoints for current state
   - WebSocket connections for real-time updates
   - Dashboard integration

## Running the Application

To start the SRE Sentinel system:

```bash
cd src
python main.py
```

This will start both the monitoring engine and the API server, providing:

- Real-time container monitoring
- AI-powered anomaly detection
- Automated incident response
- Dashboard accessible via WebSocket API
- Secure MCP Gateway integration for container operations
