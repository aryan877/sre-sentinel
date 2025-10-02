#!/bin/bash

##
# SRE Sentinel Setup Script
# Initializes the complete project environment
##

set -e

echo "🛡️  SRE Sentinel - Setup Script"
echo "========================================"
echo ""

# Check Docker
if ! docker info > /dev/null 2>&1; then
    echo "❌ Error: Docker is not running"
    exit 1
fi

echo "✓ Docker is running"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: Python 3 is not installed"
    exit 1
fi

echo "✓ Python 3 found"

# Check Node.js
if ! command -v node &> /dev/null; then
    echo "❌ Error: Node.js is not installed"
    exit 1
fi

echo "✓ Node.js found"
echo ""

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "📝 Creating .env file..."
    cp .env.example .env
    echo "⚠️  Please edit .env and add your API keys:"
    echo "   - CEREBRAS_API_KEY"
    echo "   - LLAMA_API_KEY"
    echo ""
    read -p "Press Enter when you've added your keys..."
fi

# Install Python dependencies
echo ""
echo "📦 Installing Python dependencies..."
cd src
python3 -m pip install -r requirements.txt --quiet
cd ..

# Install Node.js dependencies for dashboard
echo ""
echo "📦 Installing dashboard dependencies..."
cd dashboard
npm install --silent
cd ..

# Install MCP server dependencies
echo ""
echo "📦 Installing MCP server dependencies..."
cd mcp-servers/docker-control
npm install --silent
cd ../config-patcher
npm install --silent
cd ../..

# Build demo app
echo ""
echo "🏗️  Building demo infrastructure..."
docker-compose build

echo ""
echo "========================================"
echo "✅ Setup complete!"
echo ""
echo "🚀 Quick Start:"
echo ""
echo "1. Start everything (includes MCP Gateway):"
echo "   docker-compose up -d"
echo ""
echo "2. Start the dashboard:"
echo "   cd dashboard && npm run dev"
echo ""
echo "3. Open dashboard:"
echo "   http://localhost:5173"
echo ""
echo "4. Break something to test:"
echo "   ./scripts/break-service.sh"
echo ""
echo "📊 Dashboard: http://localhost:5173"
echo "🔧 Demo API: http://localhost:3001"
echo "🛡️ SRE Sentinel: http://localhost:8000"
echo "🔌 MCP Gateway: http://localhost:8811"
echo ""
echo "========================================"