#!/bin/bash

# Simple Backend Deployment Script
# Deploys Flask backend for HTTPS reverse proxy setup

set -e

echo "🚀 Deploying Thakii Backend for HTTPS"
echo "======================================"

# Step 1: Stop existing processes
echo "🛑 Stopping existing services..."
pkill -f "python.*app.py" || echo "No existing backend process"

# Step 2: Install dependencies
echo "📦 Installing Python dependencies..."
pip3 install -r requirements.txt

# Step 3: Set up environment
echo "⚙️ Setting up environment..."
cat > .env << 'EOL'
GOOGLE_APPLICATION_CREDENTIALS=/home/ec2-user/firebase-service-account.json
FLASK_ENV=production
FLASK_RUN_HOST=127.0.0.1
FLASK_RUN_PORT=5001
S3_BUCKET_NAME=thakii-video-storage-1753883631
AWS_DEFAULT_REGION=us-east-2
EOL

source .env
export $(cat .env | xargs)

# Step 4: Start backend
echo "🚀 Starting Flask backend on localhost:5001..."
mkdir -p logs
nohup python3 app.py > logs/backend.log 2>&1 &
BACKEND_PID=$!
echo $BACKEND_PID > backend.pid

echo "Backend started with PID: $BACKEND_PID"

# Step 5: Health check
sleep 3
if curl -f http://127.0.0.1:5001/health 2>/dev/null; then
    echo "✅ Backend is running correctly"
    curl -s http://127.0.0.1:5001/health | python3 -c "import sys, json; print(json.dumps(json.load(sys.stdin), indent=2))"
else
    echo "❌ Backend health check failed"
    echo "--- Backend logs ---"
    tail -20 logs/backend.log
    exit 1
fi

echo ""
echo "🎉 Backend deployment completed!"
echo "📍 Backend running at: http://127.0.0.1:5001"
echo "🔧 Next: Set up Nginx HTTPS proxy with: sudo ./scripts/setup-nginx-https.sh"
