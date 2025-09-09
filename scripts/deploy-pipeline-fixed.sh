#!/bin/bash

echo "🚀 Deploying backend using corrected pipeline deployment..."

# SSH into the server and deploy using the correct directory structure
ssh -o ProxyCommand="cloudflared access ssh --hostname %h" ec2-user@vps-71.fds-1.com << 'ENDSSH'

echo "📍 Current location: $(pwd)"
echo "📂 Directory contents:"
ls -la

# Navigate to the correct backend directory
cd thakii-backend-api

echo "🔄 Stopping existing services..."
# Kill any existing Python processes for the backend
pkill -f "python3 app.py" || true
pkill -f "python.*app.py" || true
sleep 3

echo "📥 Updating backend code from repository..."
git fetch origin
git reset --hard origin/main
git pull origin main

echo "🔧 Creating environment configuration..."
# Create .env file with the required Firebase configuration
cat > .env << 'ENVEOF'
# Flask Configuration
FLASK_ENV=production
FLASK_DEBUG=False
PORT=5001

# AWS Configuration
AWS_DEFAULT_REGION=us-east-2
S3_BUCKET_NAME=thakii-video-storage-1753883631

# Firebase Configuration (CRITICAL)
GOOGLE_CLOUD_PROJECT=thakii-973e3
FIREBASE_PROJECT_ID=thakii-973e3
FIREBASE_SERVICE_ACCOUNT_KEY=/home/ec2-user/firebase-service-account.json

# CORS Configuration
ALLOWED_ORIGINS=https://thakii-frontend.netlify.app,http://localhost:3000
ENVEOF

echo "📝 Created .env configuration:"
cat .env

echo "🚀 Starting backend service with correct environment..."

# Source environment
source .env
export $(cat .env | grep -v '^#' | xargs)

# Verify environment variables are set
echo "🔍 Verifying critical environment variables:"
echo "GOOGLE_CLOUD_PROJECT: $GOOGLE_CLOUD_PROJECT"
echo "FIREBASE_PROJECT_ID: $FIREBASE_PROJECT_ID"

# Create logs directory
mkdir -p logs

# Start backend with explicit environment variables
echo "🔥 Starting backend API with fixed Firebase configuration..."
GOOGLE_CLOUD_PROJECT=thakii-973e3 FIREBASE_PROJECT_ID=thakii-973e3 nohup python3 app.py > logs/backend.log 2>&1 &
BACKEND_PID=$!
echo $BACKEND_PID > backend.pid
echo "Backend started with PID: $BACKEND_PID"

# Wait for service to initialize
echo "⏳ Waiting for backend to initialize..."
sleep 15

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

echo "🔐 Testing authentication endpoint (should NOT show GOOGLE_CLOUD_PROJECT error)..."
AUTH_RESPONSE=$(curl -s -H "Authorization: Bearer invalid-token" http://127.0.0.1:5001/list)
echo "Auth test response: $AUTH_RESPONSE"

if echo "$AUTH_RESPONSE" | grep -q "GOOGLE_CLOUD_PROJECT"; then
    echo "❌ CRITICAL: Still getting GOOGLE_CLOUD_PROJECT error!"
    echo "Backend logs:"
    tail -20 logs/backend.log
else
    echo "✅ SUCCESS: Authentication error is now proper (no project ID issue)!"
fi

echo "📋 Recent backend logs:"
tail -15 logs/backend.log

echo "🎯 Testing external HTTPS endpoint..."
curl -s https://vps-71.fds-1.com/health | head -1

echo "✅ Pipeline deployment completed successfully!"

ENDSSH

echo "🎉 Backend pipeline deployment finished!"
