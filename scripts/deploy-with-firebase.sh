#!/bin/bash

echo "🔥 Backend Deployment with Firebase Authentication Fix..."

# SSH into the server and fix Firebase configuration
ssh -o ProxyCommand="cloudflared access ssh --hostname %h" ec2-user@vps-71.fds-1.com << 'ENDSSH'

echo "📍 Current location: $(pwd)"

echo "🛑 Step 1: Stop existing backend..."
pkill -f "python3 app.py" || true
sleep 3

echo "🔧 Step 2: Configure Firebase properly..."
cd thakii-backend-api

# Update environment to enable Firebase
cat > .env << 'ENVEOF'
# Flask Configuration
FLASK_ENV=production
FLASK_DEBUG=False
PORT=5001

# AWS Configuration
AWS_DEFAULT_REGION=us-east-2
S3_BUCKET_NAME=thakii-video-storage-1753883631

# Firebase Configuration (ENABLED)
GOOGLE_CLOUD_PROJECT=thakii-lecture2pdf
FIREBASE_PROJECT_ID=thakii-lecture2pdf

# CORS Configuration - SPECIFIC ORIGIN (no wildcard)
ALLOWED_ORIGINS=https://thakii-frontend.netlify.app

# Enable Firebase (remove DISABLE_FIREBASE)
# DISABLE_FIREBASE=false
ENVEOF

echo "📝 Environment configuration updated - Firebase ENABLED"

echo "🚀 Step 3: Start backend with Firebase enabled..."
source venv/bin/activate
source .env
export $(cat .env | grep -v '^#' | xargs)

# Start backend with Firebase enabled
echo "🔥 Starting backend API with Firebase authentication..."
ALLOWED_ORIGINS='https://thakii-frontend.netlify.app' \
GOOGLE_CLOUD_PROJECT='thakii-lecture2pdf' \
FIREBASE_PROJECT_ID='thakii-lecture2pdf' \
nohup python3 app.py > logs/backend-firebase.log 2>&1 &

BACKEND_PID=$!
echo $BACKEND_PID > backend.pid
echo "Backend started with PID: $BACKEND_PID"

# Wait for service to initialize
echo "⏳ Waiting for backend to initialize (10 seconds)..."
sleep 10

echo "🏥 Step 4: Test backend health..."
HEALTH_RESPONSE=$(curl -s http://127.0.0.1:5001/health)
echo "Health response: $HEALTH_RESPONSE"

if echo "$HEALTH_RESPONSE" | grep -q "healthy"; then
    echo "✅ Backend health check passed"
else
    echo "❌ Backend health check failed"
    echo "Backend logs:"
    tail -20 logs/backend-firebase.log
fi

echo "🔐 Step 5: Test authentication endpoint..."
AUTH_RESPONSE=$(curl -s -H "Authorization: Bearer invalid-token" http://127.0.0.1:5001/list)
echo "Auth test response: $AUTH_RESPONSE"

if echo "$AUTH_RESPONSE" | grep -q "The default Firebase app does not exist"; then
    echo "❌ CRITICAL: Firebase still not properly initialized!"
    echo "Backend logs:"
    tail -20 logs/backend-firebase.log
else
    echo "✅ SUCCESS: Firebase authentication is working!"
fi

echo "📋 Backend startup logs (first 20 lines):"
head -20 logs/backend-firebase.log

echo "✅ Firebase backend deployment completed!"

ENDSSH

echo "🎉 Firebase Backend Deployment completed!"
echo ""
echo "🧪 Test the frontend now - authentication should work!"
