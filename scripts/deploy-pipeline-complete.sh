#!/bin/bash

echo "🚀 Complete backend deployment with dependencies..."

# SSH into the server and deploy with full setup
ssh -o ProxyCommand="cloudflared access ssh --hostname %h" ec2-user@vps-71.fds-1.com << 'ENDSSH'

echo "📍 Current location: $(pwd)"

# Navigate to the backend directory
cd thakii-backend-api

echo "🔄 Stopping existing services..."
pkill -f "python3 app.py" || true
pkill -f "python.*app.py" || true
sleep 3

echo "📥 Updating backend code..."
git fetch origin
git reset --hard origin/main
git pull origin main

echo "🐍 Setting up Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

echo "📦 Installing Python dependencies..."
pip install -r requirements.txt

echo "🔧 Creating environment configuration..."
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

echo "📝 Environment configuration created"

echo "🚀 Starting backend with virtual environment..."
source venv/bin/activate
source .env
export $(cat .env | grep -v '^#' | xargs)

# Create logs directory
mkdir -p logs

# Start backend with the fixed Firebase configuration
echo "🔥 Starting backend API with Firebase project ID fix..."
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

echo "🔐 Testing authentication endpoint..."
AUTH_RESPONSE=$(curl -s -H "Authorization: Bearer invalid-token" http://127.0.0.1:5001/list)
echo "Auth test response: $AUTH_RESPONSE"

if echo "$AUTH_RESPONSE" | grep -q "GOOGLE_CLOUD_PROJECT"; then
    echo "❌ CRITICAL: Still getting GOOGLE_CLOUD_PROJECT error!"
    echo "Backend logs:"
    tail -20 logs/backend.log
else
    echo "✅ SUCCESS: Firebase project ID fix is working!"
fi

echo "📋 Backend initialization logs:"
head -20 logs/backend.log

echo "✅ Complete deployment finished!"

ENDSSH

echo "🎉 Complete backend deployment finished!"
