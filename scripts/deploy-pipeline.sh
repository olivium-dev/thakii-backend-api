#!/bin/bash

echo "🚀 Deploying backend using pipeline deployment..."

# SSH into the server and deploy using the pipeline approach
ssh -o ProxyCommand="cloudflared access ssh --hostname %h" ec2-user@vps-71.fds-1.com << 'ENDSSH'

echo "📍 Current location: $(pwd)"

# Navigate to the backend directory
cd thakii-backend

echo "🔄 Stopping existing services..."
if [ -f backend.pid ]; then
    echo "Stopping backend (PID: $(cat backend.pid))"
    kill $(cat backend.pid) 2>/dev/null || true
    rm backend.pid
fi

if [ -f worker.pid ]; then
    echo "Stopping worker (PID: $(cat worker.pid))"
    kill $(cat worker.pid) 2>/dev/null || true
    rm worker.pid
fi

# Wait for processes to stop
sleep 3

echo "📥 Updating backend code from repository..."
cd backend
git fetch origin
git reset --hard origin/main
git pull origin main
cd ..

echo "🔧 Configuring environment variables..."
# Ensure the critical Firebase environment variables are set
if ! grep -q "GOOGLE_CLOUD_PROJECT" .env; then
    echo "" >> .env
    echo "# Firebase Project Configuration (CRITICAL)" >> .env
    echo "GOOGLE_CLOUD_PROJECT=thakii-973e3" >> .env
fi

if ! grep -q "FIREBASE_PROJECT_ID" .env; then
    echo "FIREBASE_PROJECT_ID=thakii-973e3" >> .env
fi

echo "📝 Current .env configuration:"
cat .env | grep -E "(GOOGLE_CLOUD_PROJECT|FIREBASE_PROJECT_ID|FIREBASE_SERVICE_ACCOUNT_KEY)"

echo "🚀 Starting backend services with pipeline deployment..."

# Source environment
source .env
export $(cat .env | grep -v '^#' | xargs)

# Verify environment variables are set
echo "🔍 Verifying environment variables:"
echo "GOOGLE_CLOUD_PROJECT: $GOOGLE_CLOUD_PROJECT"
echo "FIREBASE_PROJECT_ID: $FIREBASE_PROJECT_ID"

# Create logs directory
mkdir -p logs

# Start backend with explicit environment variables
echo "🔥 Starting backend API..."
GOOGLE_CLOUD_PROJECT=thakii-973e3 FIREBASE_PROJECT_ID=thakii-973e3 nohup python3 backend/api/app.py > logs/backend.log 2>&1 &
BACKEND_PID=$!
echo $BACKEND_PID > backend.pid
echo "Backend started with PID: $BACKEND_PID"

# Start worker with explicit environment variables
echo "⚙️ Starting worker service..."
GOOGLE_CLOUD_PROJECT=thakii-973e3 FIREBASE_PROJECT_ID=thakii-973e3 nohup python3 backend/worker/worker.py > logs/worker.log 2>&1 &
WORKER_PID=$!
echo $WORKER_PID > worker.pid
echo "Worker started with PID: $WORKER_PID"

# Wait for services to initialize
echo "⏳ Waiting for services to initialize..."
sleep 10

echo "🏥 Testing backend health..."
HEALTH_RESPONSE=$(curl -s http://127.0.0.1:5001/health)
echo "Health response: $HEALTH_RESPONSE"

if echo "$HEALTH_RESPONSE" | grep -q "healthy"; then
    echo "✅ Backend health check passed"
else
    echo "❌ Backend health check failed"
    echo "Backend logs:"
    tail -20 logs/backend.log
fi

echo "🔐 Testing authentication endpoint..."
AUTH_RESPONSE=$(curl -s -H "Authorization: Bearer invalid-token" http://127.0.0.1:5001/list)
echo "Auth test response: $AUTH_RESPONSE"

if echo "$AUTH_RESPONSE" | grep -q "GOOGLE_CLOUD_PROJECT"; then
    echo "❌ CRITICAL: Still getting GOOGLE_CLOUD_PROJECT error!"
    echo "Backend logs:"
    tail -20 logs/backend.log
else
    echo "✅ Authentication error is now proper (no project ID issue)"
fi

echo "📋 Recent backend logs:"
tail -10 logs/backend.log

echo "✅ Pipeline deployment completed!"

ENDSSH

echo "�� Backend pipeline deployment finished!"
