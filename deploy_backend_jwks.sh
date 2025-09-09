#!/bin/bash
echo "🔄 Stopping existing backend..."
ssh -o ProxyCommand="cloudflared access ssh --hostname %h" ec2-user@vps-71.fds-1.com "pkill -f 'python3 app.py' || true"
sleep 3

echo "📥 Updating code..."
ssh -o ProxyCommand="cloudflared access ssh --hostname %h" ec2-user@vps-71.fds-1.com "cd thakii-backend-api && git fetch origin && git reset --hard origin/main && git pull origin main"

echo "🔧 Installing dependencies..."
ssh -o ProxyCommand="cloudflared access ssh --hostname %h" ec2-user@vps-71.fds-1.com "cd thakii-backend-api && source venv/bin/activate && pip install -r requirements.txt && pip install PyJWT requests"

echo "🔧 Configuring environment..."
ssh -o ProxyCommand="cloudflared access ssh --hostname %h" ec2-user@vps-71.fds-1.com 'cd thakii-backend-api && cat > .env << "ENVEOF"
# Flask Configuration
FLASK_ENV=production
FLASK_DEBUG=False
PORT=5001

# AWS Configuration
AWS_DEFAULT_REGION=us-east-2
S3_BUCKET_NAME=thakii-video-storage-1753883631

# Firebase Configuration (ENABLED with JWKS fallback)
GOOGLE_CLOUD_PROJECT=thakii-973e3
FIREBASE_PROJECT_ID=thakii-973e3

# CORS Configuration
ALLOWED_ORIGINS=https://thakii-frontend.netlify.app
ENVEOF'

echo "🚀 Starting backend..."
ssh -o ProxyCommand="cloudflared access ssh --hostname %h" ec2-user@vps-71.fds-1.com "cd thakii-backend-api && source venv/bin/activate && source .env && mkdir -p logs && nohup python3 app.py > logs/backend-jwks.log 2>&1 & echo \$! > backend.pid"

echo "⏳ Waiting for startup..."
sleep 10

echo "🏥 Testing health..."
ssh -o ProxyCommand="cloudflared access ssh --hostname %h" ec2-user@vps-71.fds-1.com "curl -f http://127.0.0.1:5001/health || echo 'Health check failed'"

echo "🔐 Testing auth with invalid token..."
ssh -o ProxyCommand="cloudflared access ssh --hostname %h" ec2-user@vps-71.fds-1.com "curl -H 'Authorization: Bearer invalid-token' http://127.0.0.1:5001/list"

echo "✅ Deployment complete"
