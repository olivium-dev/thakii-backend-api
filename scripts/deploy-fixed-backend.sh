#!/bin/bash

echo "🚀 Deploying fixed backend with proper Firebase configuration..."

# SSH into the server and deploy the fix
ssh -o ProxyCommand="cloudflared access ssh --hostname %h" ec2-user@vps-71.fds-1.com << 'ENDSSH'

echo "📍 Current location: $(pwd)"

# Navigate to backend directory
cd thakii-backend

echo "🔄 Stopping existing services..."
pkill -f "python3 backend/api/app.py" || true
pkill -f "python3 backend/worker/worker.py" || true
sleep 3

# Remove old PID files
rm -f backend.pid worker.pid

echo "📥 Pulling latest changes from backend repository..."
cd backend
git pull origin main || echo "Git pull failed, continuing with local changes"
cd ..

echo "🔧 Updating environment configuration..."
# Ensure the environment variables are set
if ! grep -q "GOOGLE_CLOUD_PROJECT" .env; then
    echo "" >> .env
    echo "# Firebase Project Configuration" >> .env
    echo "GOOGLE_CLOUD_PROJECT=thakii-973e3" >> .env
    echo "FIREBASE_PROJECT_ID=thakii-973e3" >> .env
fi

echo "📝 Current .env file:"
cat .env

echo "🚀 Starting backend with explicit environment..."
source .env
export $(cat .env | grep -v '^#' | xargs)

# Start backend with explicit environment variables
GOOGLE_CLOUD_PROJECT=thakii-973e3 FIREBASE_PROJECT_ID=thakii-973e3 nohup python3 backend/api/app.py > logs/backend.log 2>&1 &
BACKEND_PID=$!
echo $BACKEND_PID > backend.pid
echo "Backend started with PID: $BACKEND_PID"

# Start worker with explicit environment variables
GOOGLE_CLOUD_PROJECT=thakii-973e3 FIREBASE_PROJECT_ID=thakii-973e3 nohup python3 backend/worker/worker.py > logs/worker.log 2>&1 &
WORKER_PID=$!
echo $WORKER_PID > worker.pid
echo "Worker started with PID: $WORKER_PID"

# Wait for services to start
sleep 10

echo "🏥 Testing backend health..."
curl -f http://127.0.0.1:5001/health || echo "❌ Health check failed"

echo "🔐 Testing authentication (should show proper error without project ID issue)..."
curl -H "Authorization: Bearer invalid-token" http://127.0.0.1:5001/list

echo "📋 Checking backend logs for Firebase initialization..."
tail -10 logs/backend.log

echo "✅ Backend deployment completed!"

ENDSSH

echo "🎉 Fixed backend deployment script completed!"
