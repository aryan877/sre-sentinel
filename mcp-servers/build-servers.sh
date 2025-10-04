#!/bin/bash

# Build script for MCP servers

set -e

echo "Building MCP server images..."

# Build docker-control server
echo "Building docker-control server..."
cd docker-control
docker build -t mcp-servers/docker-control:latest .
cd ..

# Build config-patcher server
echo "Building config-patcher server..."
cd config-patcher
docker build -t mcp-servers/config-patcher:latest .
cd ..

# Verify images were created
echo "Verifying built images..."
docker images | grep mcp-servers

echo "MCP server images built successfully!"