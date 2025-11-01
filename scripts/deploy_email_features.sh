#!/bin/bash

echo "🚀 Deploying Email Notification Features to Thakii Backend"
echo "=========================================================="

# Configuration
SERVER_HOST="192.168.2.71"
SERVER_USER="ec2-user"
SERVER_PASSWORD="P@ssw0rd768"
DB_HOST="localhost"
DB_PORT="5432"
DB_NAME="thakii_production"
DB_USER="thakii_user"
DB_PASSWORD="P@ssw0rd768_DB"

echo "📋 Deployment Steps:"
echo "1. Upload new backend files"
echo "2. Run database migration"
echo "3. Restart backend service"
echo "4. Test email configuration"
echo ""

# Step 1: Upload files to server
echo "📤 Step 1: Uploading backend files..."
sshpass -p "$SERVER_PASSWORD" scp -r \
  core/email_service.py \
  scripts/add_email_notifications_table.sql \
  test_email_service.py \
  EMAIL_CONFIG.env.example \
  EMAIL_NOTIFICATIONS_GUIDE.md \
  "$SERVER_USER@$SERVER_HOST:~/thakii-backend-api/"

if [ $? -eq 0 ]; then
    echo "✅ Files uploaded successfully"
else
    echo "❌ Failed to upload files"
    exit 1
fi

# Step 2: Run database migration
echo ""
echo "🗄️  Step 2: Running database migration..."
sshpass -p "$SERVER_PASSWORD" ssh "$SERVER_USER@$SERVER_HOST" << EOF
cd ~/thakii-backend-api

# Run the database migration
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -f scripts/add_email_notifications_table.sql

if [ \$? -eq 0 ]; then
    echo "✅ Database migration completed successfully"
else
    echo "❌ Database migration failed"
    exit 1
fi
EOF

if [ $? -ne 0 ]; then
    echo "❌ Database migration failed"
    exit 1
fi

# Step 3: Restart backend service
echo ""
echo "🔄 Step 3: Restarting backend service..."
sshpass -p "$SERVER_PASSWORD" ssh "$SERVER_USER@$SERVER_HOST" << 'EOF'
cd ~/thakii-backend-api

# Stop existing backend
pkill -f "python3 app.py" || true
sleep 3

# Start backend with updated code
source venv/bin/activate
nohup python3 app.py > logs/backend.log 2>&1 &
BACKEND_PID=$!
echo $BACKEND_PID > backend.pid

echo "✅ Backend restarted with PID: $BACKEND_PID"

# Wait for service to initialize
echo "⏳ Waiting for backend to initialize..."
sleep 10

# Test backend health
HEALTH_RESPONSE=$(curl -s http://127.0.0.1:5001/health)
if echo "$HEALTH_RESPONSE" | grep -q "healthy"; then
    echo "✅ Backend health check passed"
else
    echo "❌ Backend health check failed"
    echo "Response: $HEALTH_RESPONSE"
fi
EOF

if [ $? -ne 0 ]; then
    echo "❌ Backend restart failed"
    exit 1
fi

# Step 4: Test email configuration
echo ""
echo "📧 Step 4: Testing email configuration..."
echo ""
echo "To test email functionality:"
echo "1. SSH to the server: ssh $SERVER_USER@$SERVER_HOST"
echo "2. Navigate to backend: cd ~/thakii-backend-api"
echo "3. Configure email in .env file (see EMAIL_CONFIG.env.example)"
echo "4. Run email test: python3 test_email_service.py"
echo ""
echo "Admin API endpoints are now available:"
echo "- GET  /admin/email/config - View email configuration"
echo "- POST /admin/email/test - Send test email"
echo "- POST /admin/email/recipients - Update additional recipients"
echo ""

echo "🎉 Email notification features deployed successfully!"
echo ""
echo "📖 Next Steps:"
echo "1. Configure SMTP settings in .env file on the server"
echo "2. Test email functionality using the test script"
echo "3. Configure additional notification recipients via admin API"
echo "4. Monitor email delivery in backend logs"
echo ""
echo "📚 Documentation: EMAIL_NOTIFICATIONS_GUIDE.md"



