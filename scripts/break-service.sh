#!/bin/bash

##
# Break Service Script
# Simulates various failure scenarios for demo purposes
##

set -e

echo "🔧 SRE Sentinel Demo: Breaking Service"
echo "========================================"
echo ""

# Check if docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Error: Docker is not running"
    exit 1
fi

# Menu
echo "Choose a failure scenario:"
echo ""
echo "1) Trigger database connection errors (API logs errors)"
echo "2) Trigger memory leak in API (OOM crash)"
echo "3) Remove critical environment variable (config error)"
echo "4) Max out container CPU (performance degradation)"
echo "5) Trigger application exception (unhandled error)"
echo ""
read -p "Enter choice [1-5]: " choice

case $choice in
    1)
        echo ""
        echo "💥 Scenario 1: Triggering database connection errors..."
        # Make API connect to wrong database to generate error logs
        docker exec demo-api sh -c "curl -s http://localhost:3001/db-check > /dev/null" || true
        echo "✓ Database connection errors triggered."
        echo ""
        echo "Watch the logs:"
        echo "  docker logs -f demo-api"
        echo ""
        echo "SRE Sentinel should:"
        echo "  1. Detect connection errors in logs"
        echo "  2. Analyze logs and docker-compose.yml"
        echo "  3. Suggest fixes for database connection"
        ;;

    2)
        echo ""
        echo "💥 Scenario 2: Triggering memory leak..."
        echo "Sending requests to /leak endpoint..."

        for i in {1..10}; do
            curl -s http://localhost:3001/leak > /dev/null && echo "  Request $i sent"
            sleep 0.5
        done

        echo "✓ Memory leak triggered. Container will crash soon."
        echo ""
        echo "Watch memory usage:"
        echo "  docker stats demo-api"
        echo ""
        echo "SRE Sentinel should:"
        echo "  1. Detect OOM errors in logs"
        echo "  2. Identify memory leak pattern"
        echo "  3. Increase memory limits and restart"
        ;;

    3)
        echo ""
        echo "💥 Scenario 3: Removing DATABASE_URL environment variable..."

        # Stop and remove container
        docker stop demo-api
        docker rm demo-api

        # Restart without DATABASE_URL
        docker run -d \
            --name demo-api \
            --network sre-sentinel-network \
            --label sre-sentinel.monitor=true \
            --label sre-sentinel.service=api \
            -p 3001:3001 \
            -v "$(pwd)/demo-app/server.js:/app/server.js" \
            -w /app \
            node:20-alpine \
            sh -c "npm install express && node server.js"

        echo "✓ API restarted without DATABASE_URL"
        echo ""
        echo "SRE Sentinel should:"
        echo "  1. Detect database connection errors"
        echo "  2. Analyze missing environment variable"
        echo "  3. Patch config with correct DATABASE_URL"
        ;;

    4)
        echo ""
        echo "💥 Scenario 4: Maxing out CPU..."
        docker exec demo-api sh -c "while true; do :; done" &
        PID=$!

        echo "✓ CPU stress started (PID: $PID)"
        echo ""
        echo "To stop: kill $PID"
        echo ""
        echo "SRE Sentinel should:"
        echo "  1. Detect high CPU usage"
        echo "  2. Identify runaway process"
        echo "  3. Restart container or adjust CPU limits"
        ;;

    5)
        echo ""
        echo "💥 Scenario 5: Triggering application exception..."
        # Trigger an unhandled exception in the API
        curl -s http://localhost:3001/error > /dev/null 2>&1 || true
        echo "✓ Application exception triggered."
        echo ""
        echo "Watch the logs:"
        echo "  docker logs -f demo-api"
        echo ""
        echo "SRE Sentinel should:"
        echo "  1. Detect unhandled exception in logs"
        echo "  2. Analyze error stack trace"
        echo "  3. Suggest code fix or restart"
        ;;
    *)
        echo "Invalid choice"
        exit 1
        ;;
esac

echo ""
echo "=========================================="
echo "✓ Scenario triggered successfully"
echo ""
echo "Now watch SRE Sentinel work its magic! 🛡️"
echo ""