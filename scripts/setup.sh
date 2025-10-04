#!/bin/bash

##
# SRE Sentinel - Simple Setup Script
# Sets up the environment and builds necessary images
##

set -e

echo "🛡️  SRE Sentinel - Setup"
echo "================================"
echo ""

# Check prerequisites
echo "Checking prerequisites..."

if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running"
    exit 1
fi
echo "✓ Docker is running"

if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed"
    exit 1
fi
echo "✓ Python 3 found"

if ! command -v node &> /dev/null; then
    echo "❌ Node.js is not installed"
    exit 1
fi
echo "✓ Node.js found"

echo ""

# Environment setup
if [ ! -f .env ]; then
    echo "📝 Creating .env file from .env.example..."
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "⚠️  Please edit .env and add your API keys:"
        echo "   - CEREBRAS_API_KEY"
        echo "   - LLAMA_API_KEY"
        echo ""
        read -p "Press Enter when ready to continue..."
    else
        echo "❌ .env.example not found!"
        exit 1
    fi
fi

# Install Python dependencies
echo ""
echo "📦 Installing Python dependencies..."
python3 -m pip install -r src/requirements.txt --quiet

# Build MCP server images
echo ""
echo "🐳 Building MCP server images..."
cd mcp-servers
chmod +x build-servers.sh
./build-servers.sh
cd ..

# Build main application
echo ""
echo "🏗️  Building SRE Sentinel..."
docker compose build

echo ""
echo "================================"
echo "✅ Setup complete!"
echo ""
echo "🚀 Quick Start:"
echo ""
echo "1. Start all services:"
echo "   docker compose up -d"
echo ""
echo "2. View logs:"
echo "   docker compose logs -f"
echo ""
echo "3. Stop services:"
echo "   docker compose down"
echo ""
echo "📊 Services:"
echo "   • Demo API: http://localhost:3001"
echo "   • SRE Sentinel: http://localhost:8000"
echo "   • MCP Gateway: http://localhost:8811"
echo "   • PostgreSQL: localhost:5432"
echo "   • Redis: localhost:6379"
echo ""
echo "================================"
