#!/bin/bash
# Script to enable Redis Queue in the backend

# Get the directory of the script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"

# Path to .env file
ENV_FILE="$BACKEND_DIR/.env"

# Backup current .env file
cp "$ENV_FILE" "$ENV_FILE.backup-$(date +%Y%m%d%H%M%S)"

echo "📝 Updating environment variables..."

# Check if ENABLE_REDIS_QUEUE already exists
if grep -q "ENABLE_REDIS_QUEUE" "$ENV_FILE"; then
    # Update existing value
    sed -i '' 's/ENABLE_REDIS_QUEUE=.*/ENABLE_REDIS_QUEUE=true/' "$ENV_FILE"
else
    # Add new value
    echo "ENABLE_REDIS_QUEUE=true" >> "$ENV_FILE"
fi

# Check if REDIS_HOST already exists
if grep -q "REDIS_HOST" "$ENV_FILE"; then
    # Update existing value
    sed -i '' 's/REDIS_HOST=.*/REDIS_HOST=localhost/' "$ENV_FILE"
else
    # Add new value
    echo "REDIS_HOST=localhost" >> "$ENV_FILE"
fi

# Check if REDIS_PORT already exists
if grep -q "REDIS_PORT" "$ENV_FILE"; then
    # Update existing value
    sed -i '' 's/REDIS_PORT=.*/REDIS_PORT=6379/' "$ENV_FILE"
else
    # Add new value
    echo "REDIS_PORT=6379" >> "$ENV_FILE"
fi

echo "✅ Environment variables updated:"
grep -E "ENABLE_REDIS_QUEUE|REDIS_HOST|REDIS_PORT" "$ENV_FILE"

echo ""
echo "🔄 To apply changes, restart the backend service:"
echo "launchctl unload ~/Library/LaunchAgents/com.thakii.backend.plist"
echo "launchctl load -w ~/Library/LaunchAgents/com.thakii.backend.plist"

echo ""
echo "🔄 To start the RQ worker:"
echo "launchctl load -w ~/Library/LaunchAgents/com.thakii.rq_worker.plist"

echo ""
echo "🔍 To verify Redis is enabled, check:"
echo "curl -s http://localhost:5000/health | grep -E 'redis_queue|workers'"
