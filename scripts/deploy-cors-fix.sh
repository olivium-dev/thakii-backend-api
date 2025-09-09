#!/bin/bash

echo "🔧 CORS Fix Deployment Pipeline - Fixing duplicate headers issue..."

# SSH into the server and fix CORS configuration
ssh -o ProxyCommand="cloudflared access ssh --hostname %h" ec2-user@vps-71.fds-1.com << 'ENDSSH'

echo "📍 Current location: $(pwd)"

echo "🛑 Step 1: Stop existing services..."
pkill -f "python3 app.py" || true
pkill -f "python.*app.py" || true
sleep 3

echo "📥 Step 2: Update backend code..."
cd thakii-backend-api
git fetch origin
git reset --hard origin/main
git pull origin main

echo "🔧 Step 3: Fix Nginx CORS configuration (remove duplicate headers)..."
sudo cp /etc/nginx/sites-available/thakii-backend.conf /etc/nginx/sites-available/thakii-backend.conf.backup

# Create fixed Nginx config without duplicate CORS headers
sudo tee /etc/nginx/sites-available/thakii-backend.conf > /dev/null << 'NGINXEOF'
# Nginx configuration for Thakii Backend HTTPS
# This sets up a reverse proxy from HTTPS (port 443) to Flask backend (port 5001)

server {
    listen 80;
    server_name thakii-02.fanusdigital.site;
    
    # Redirect HTTP to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name thakii-02.fanusdigital.site;

    # SSL Configuration
    ssl_certificate /etc/ssl/certs/thakii.crt;
    ssl_certificate_key /etc/ssl/private/thakii.key;
    
    # Modern SSL configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512:ECDHE-RSA-AES256-GCM-SHA384:DHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # Security headers (NO CORS - let Flask handle it)
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options DENY always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # Handle all requests
    location / {
        # Handle preflight OPTIONS requests (let Flask handle CORS)
        if ($request_method = 'OPTIONS') {
            return 204;
        }

        # Proxy to Flask backend
        proxy_pass http://127.0.0.1:5001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Handle large file uploads
        client_max_body_size 500M;
        proxy_connect_timeout 300s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
        
        # Buffer settings for large uploads
        proxy_buffering off;
        proxy_request_buffering off;
    }

    # Logging
    access_log /var/log/nginx/thakii-backend.access.log;
    error_log /var/log/nginx/thakii-backend.error.log;
}
NGINXEOF

echo "✅ Nginx configuration updated (removed duplicate CORS headers)"

echo "🧪 Step 4: Test Nginx configuration..."
sudo nginx -t
if [ $? -eq 0 ]; then
    echo "✅ Nginx configuration is valid"
    sudo systemctl reload nginx
    sudo systemctl restart nginx
    echo "✅ Nginx restarted successfully"
else
    echo "❌ Nginx configuration error - restoring backup"
    sudo cp /etc/nginx/sites-available/thakii-backend.conf.backup /etc/nginx/sites-available/thakii-backend.conf
    exit 1
fi

echo "🐍 Step 5: Setup Python environment..."
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

echo "🔧 Step 6: Configure Flask CORS with specific origin..."
cat > .env << 'ENVEOF'
# Flask Configuration
FLASK_ENV=production
FLASK_DEBUG=False
PORT=5001

# AWS Configuration
AWS_DEFAULT_REGION=us-east-2
S3_BUCKET_NAME=thakii-video-storage-1753883631

# Firebase Configuration (CRITICAL)
GOOGLE_CLOUD_PROJECT=thakii-lecture2pdf
FIREBASE_PROJECT_ID=thakii-lecture2pdf
FIREBASE_SERVICE_ACCOUNT_KEY=/home/ec2-user/firebase-service-account.json

# CORS Configuration - SPECIFIC ORIGIN (no wildcard)
ALLOWED_ORIGINS=https://thakii-frontend.netlify.app
ENVEOF

echo "📝 Environment configuration created with specific CORS origin"

echo "🚀 Step 7: Start Flask backend with fixed CORS..."
source venv/bin/activate
source .env
export $(cat .env | grep -v '^#' | xargs)

# Create logs directory
mkdir -p logs

# Start backend with the fixed CORS configuration
echo "🔥 Starting backend API with CORS fix..."
ALLOWED_ORIGINS='https://thakii-frontend.netlify.app' GOOGLE_CLOUD_PROJECT='thakii-lecture2pdf' FIREBASE_PROJECT_ID='thakii-lecture2pdf' nohup python3 app.py > logs/backend-cors-fix.log 2>&1 &
BACKEND_PID=$!
echo $BACKEND_PID > backend.pid
echo "Backend started with PID: $BACKEND_PID"

# Wait for service to initialize
echo "⏳ Waiting for backend to initialize..."
sleep 10

echo "🏥 Step 8: Test backend health..."
HEALTH_RESPONSE=$(curl -s http://127.0.0.1:5001/health)
echo "Health response: $HEALTH_RESPONSE"

if echo "$HEALTH_RESPONSE" | grep -q "healthy"; then
    echo "✅ Backend health check passed"
else
    echo "❌ Backend health check failed"
    echo "Backend logs:"
    tail -20 logs/backend-cors-fix.log
fi

echo "🌐 Step 9: Test CORS configuration..."
echo "Testing CORS preflight request..."
CORS_RESPONSE=$(curl -s -H "Origin: https://thakii-frontend.netlify.app" \
                     -H "Access-Control-Request-Method: GET" \
                     -H "Access-Control-Request-Headers: authorization,content-type" \
                     -X OPTIONS \
                     https://thakii-02.fanusdigital.site/health -v 2>&1)

echo "CORS test response:"
echo "$CORS_RESPONSE" | grep -i "access-control"

# Check for duplicate headers
if echo "$CORS_RESPONSE" | grep -i "access-control-allow-origin" | grep -q ","; then
    echo "❌ CRITICAL: Still getting duplicate CORS headers!"
    echo "Full CORS response:"
    echo "$CORS_RESPONSE"
else
    echo "✅ SUCCESS: CORS headers are clean (no duplicates)!"
fi

echo "📋 Backend initialization logs:"
head -20 logs/backend-cors-fix.log

echo "✅ CORS fix deployment completed!"

ENDSSH

echo "🎉 CORS Fix Deployment Pipeline completed!"
echo ""
echo "🧪 Next steps:"
echo "1. Test the frontend at https://thakii-frontend.netlify.app"
echo "2. Check browser console for CORS errors"
echo "3. Verify API calls are working"
