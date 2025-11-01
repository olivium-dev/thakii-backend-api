#!/bin/bash
# Script to check if backend service logs are properly configured

echo "🔍 CHECKING BACKEND LOGGING CONFIGURATION"
echo "========================================"
echo ""

echo "1. Checking systemd service configuration..."
sudo systemctl cat thakii-backend.service | grep -E "StandardOutput|StandardError|SyslogIdentifier"

echo ""
echo "2. Checking if backend service is running..."
sudo systemctl status thakii-backend.service --no-pager | head -20

echo ""
echo "3. Checking recent backend logs (last 50 lines)..."
sudo journalctl -u thakii-backend.service --no-pager -n 50 | tail -30

echo ""
echo "4. Checking if print() statements are being captured..."
sudo journalctl -u thakii-backend.service --no-pager -n 200 | grep -E "print|Video uploaded to S3|Task created in PostgreSQL" | tail -10

echo ""
echo "5. Checking backend process and Python execution..."
ps aux | grep "[p]ython.*app.py" || echo "No backend process found!"

echo ""
echo "6. Testing if new code was actually loaded..."
cd /home/ec2-user/thakii-backend-api
git log -1 --oneline
echo ""
echo "Expected commit: 3c7f2dc (Debug: Add comprehensive logging...)"

