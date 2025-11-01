#!/bin/bash

BACKEND_URL="https://thakii-02.fanusdigital.site/thakii-be"
FIREBASE_TOKEN="eyJhbGciOiJSUzI1NiIsImtpZCI6IjdlYTA5ZDA1NzI2MmU2M2U2MmZmNzNmMDNlMDRhZDI5ZDg5Zjg5MmEiLCJ0eXAiOiJKV1QifQ.eyJuYW1lIjoiT3VkYXkgS2hhbGVkIiwicGljdHVyZSI6Imh0dHBzOi8vbGgzLmdvb2dsZXVzZXJjb250ZW50LmNvbS9hL0FDZzhvY0pZYjVOMlJ2Q295WkJWWnV3OWlLUmVkYmVKYlJfUTMxbWlBX0Z3WWNpY1BmN3p3blk9czk2LWMiLCJpc3MiOiJodHRwczovL3NlY3VyZXRva2VuLmdvb2dsZS5jb20vdGhha2lpLTk3M2UzIiwiYXVkIjoidGhha2lpLTk3M2UzIiwiYXV0aF90aW1lIjoxNzYxNDkwMjg5LCJ1c2VyX2lkIjoiV1cwTU13R2dxYlpzYXV5dDBuRnpaQjFSa2JkMiIsInN1YiI6IldXME1Nd0dncWJac2F1eXQwbkZ6WkIxUmtiZDIiLCJpYXQiOjE3NjE0OTAyODksImV4cCI6MTc2MTQ5Mzg4OSwiZW1haWwiOiJvdWRheS5raGFsZWRAZ21haWwuY29tIiwiZW1haWxfdmVyaWZpZWQiOnRydWUsImZpcmViYXNlIjp7ImlkZW50aXRpZXMiOnsiZ29vZ2xlLmNvbSI6WyIxMDA4NDI4NTgyNTQ2MTUwNjkwNTMiXSwiZW1haWwiOlsib3VkYXkua2hhbGVkQGdtYWlsLmNvbSJdfSwic2lnbl9pbl9wcm92aWRlciI6Imdvb2dsZS5jb20ifX0.iV0cFk-GdrHMTQEMB1O6W8SVX-SeG3IKuQWJkbGdEdoZH3N7d5cU9MaR2QS4i6ZUkXJKGSGIfQRBXV2K7JOAAK401rq6wXUJP5WGKMkPaLhgRsXIGICqb0iI1BBqgYGFGV-icEM3holnAebgXVP1ReH9PkPbBDCBHhcvRQLGYioMF39NMKqMbLXfxpJ01I7Smk36NCpK8UoQlYjYp4gEGUNndksLb_R7zzQGpPZL2Wk4UbHZ274wvpLFWrboktf5xR8k2T6W-yldj_NgP16Ai9pxAG107EwrC830QuhywTbYerUIwLZeOzB71i82aKcgj1Bgl_GV01pjjYsr2QJBzA"

echo "=========================================="
echo "🧪 TESTING THAKII BACKEND API FLOW"
echo "=========================================="
echo ""

# Step 1: Test Health
echo "📊 Step 1: Testing Health Endpoint"
echo "GET $BACKEND_URL/health"
echo "---"
curl -s "$BACKEND_URL/health" | python3 -m json.tool
echo ""
echo ""

# Step 2: Exchange Firebase token for custom token
echo "📝 Step 2: Exchange Firebase Token for Custom Backend Token"
echo "POST $BACKEND_URL/auth/exchange"
echo "---"
EXCHANGE_RESPONSE=$(curl -s -X POST "$BACKEND_URL/auth/exchange" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $FIREBASE_TOKEN" \
  -d '{}')

echo "$EXCHANGE_RESPONSE" | python3 -m json.tool
echo ""

# Extract custom token
CUSTOM_TOKEN=$(echo "$EXCHANGE_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('custom_token', ''))" 2>/dev/null)

if [ -z "$CUSTOM_TOKEN" ]; then
  echo "❌ Failed to get custom token!"
  exit 1
fi

echo "✅ Got custom token: ${CUSTOM_TOKEN:0:50}..."
echo ""
echo ""

# Step 3: Get current user info
echo "👤 Step 3: Get Current User Info"
echo "GET $BACKEND_URL/auth/user"
echo "---"
curl -s "$BACKEND_URL/auth/user" \
  -H "Authorization: Bearer $CUSTOM_TOKEN" | python3 -m json.tool
echo ""
echo ""

# Step 4: List videos
echo "📋 Step 4: List User Videos"
echo "GET $BACKEND_URL/list"
echo "---"
curl -s "$BACKEND_URL/list" \
  -H "Authorization: Bearer $CUSTOM_TOKEN" | python3 -m json.tool | head -50
echo ""
echo ""

# Step 5: Create a small test file
echo "📦 Step 5: Creating Test Video File"
TEST_FILE="/tmp/test_video_$(date +%s).mp4"
echo "Creating test file: $TEST_FILE"
dd if=/dev/zero of="$TEST_FILE" bs=1024 count=100 2>/dev/null
echo "✅ Created test file (100KB)"
echo ""
echo ""

# Step 6: Upload video
echo "⬆️  Step 6: Upload Test Video"
echo "POST $BACKEND_URL/upload"
echo "---"
UPLOAD_RESPONSE=$(curl -s -X POST "$BACKEND_URL/upload" \
  -H "Authorization: Bearer $CUSTOM_TOKEN" \
  -F "file=@$TEST_FILE")

echo "$UPLOAD_RESPONSE" | python3 -m json.tool
echo ""

# Extract video_id
VIDEO_ID=$(echo "$UPLOAD_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('video_id', ''))" 2>/dev/null)

if [ -z "$VIDEO_ID" ]; then
  echo "❌ Failed to upload video!"
  rm -f "$TEST_FILE"
  exit 1
fi

echo "✅ Video uploaded with ID: $VIDEO_ID"
echo ""
echo ""

# Step 7: Check video status in database
echo "🔍 Step 7: Check Video Status in Database"
echo "---"
sshpass -p 'P@ssw0rd768' ssh ec2-user@192.168.2.71 \
  "PGPASSWORD='P@ssw0rd768_DB' psql -h localhost -p 5432 -U thakii_user -d thakii_production -c \"SELECT video_id, filename, status, user_email, processed_by_worker, created_at FROM video_tasks WHERE video_id = '$VIDEO_ID';\""
echo ""
echo ""

# Step 8: Monitor for 20 seconds
echo "⏱️  Step 8: Monitoring Video Processing (20 seconds)"
echo "---"
for i in {1..4}; do
  sleep 5
  echo "Check $i/4:"
  sshpass -p 'P@ssw0rd768' ssh ec2-user@192.168.2.71 \
    "PGPASSWORD='P@ssw0rd768_DB' psql -h localhost -p 5432 -U thakii_user -d thakii_production -t -c \"SELECT status FROM video_tasks WHERE video_id = '$VIDEO_ID';\"" | xargs
done
echo ""
echo ""

# Step 9: Final status
echo "✅ Step 9: Final Video Status"
echo "---"
curl -s "$BACKEND_URL/list" \
  -H "Authorization: Bearer $CUSTOM_TOKEN" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for video in data.get('videos', []):
    if video.get('video_id') == '$VIDEO_ID':
        print(json.dumps(video, indent=2))
        break
"
echo ""
echo ""

# Step 10: Check backend logs for email activity
echo "📧 Step 10: Check Backend Logs for Email Activity"
echo "---"
sshpass -p 'P@ssw0rd768' ssh ec2-user@192.168.2.71 \
  "cd ~/thakii-backend-api && tail -50 logs/backend.log | grep -E '(Email|email|Brevo|$VIDEO_ID)' | tail -20"
echo ""
echo ""

# Cleanup
rm -f "$TEST_FILE"

echo "=========================================="
echo "✅ TEST COMPLETE!"
echo "=========================================="
