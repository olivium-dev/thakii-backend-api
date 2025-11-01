#!/bin/bash

BACKEND_URL="https://thakii-02.fanusdigital.site/thakii-be"
FIREBASE_TOKEN="eyJhbGciOiJSUzI1NiIsImtpZCI6IjdlYTA5ZDA1NzI2MmU2M2U2MmZmNzNmMDNlMDRhZDI5ZDg5Zjg5MmEiLCJ0eXAiOiJKV1QifQ.eyJuYW1lIjoiT3VkYXkgS2hhbGVkIiwicGljdHVyZSI6Imh0dHBzOi8vbGgzLmdvb2dsZXVzZXJjb250ZW50LmNvbS9hL0FDZzhvY0pZYjVOMlJ2Q295WkJWWnV3OWlLUmVkYmVKYlJfUTMxbWlBX0Z3WWNpY1BmN3p3blk9czk2LWMiLCJpc3MiOiJodHRwczovL3NlY3VyZXRva2VuLmdvb2dsZS5jb20vdGhha2lpLTk3M2UzIiwiYXVkIjoidGhha2lpLTk3M2UzIiwiYXV0aF90aW1lIjoxNzYxNDkwMjg5LCJ1c2VyX2lkIjoiV1cwTU13R2dxYlpzYXV5dDBuRnpaQjFSa2JkMiIsInN1YiI6IldXME1Nd0dncWJac2F1eXQwbkZ6WkIxUmtiZDIiLCJpYXQiOjE3NjE0OTAyODksImV4cCI6MTc2MTQ5Mzg4OSwiZW1haWwiOiJvdWRheS5raGFsZWRAZ21haWwuY29tIiwiZW1haWxfdmVyaWZpZWQiOnRydWUsImZpcmViYXNlIjp7ImlkZW50aXRpZXMiOnsiZ29vZ2xlLmNvbSI6WyIxMDA4NDI4NTgyNTQ2MTUwNjkwNTMiXSwiZW1haWwiOlsib3VkYXkua2hhbGVkQGdtYWlsLmNvbSJdfSwic2lnbl9pbl9wcm92aWRlciI6Imdvb2dsZS5jb20ifX0.iV0cFk-GdrHMTQEMB1O6W8SVX-SeG3IKuQWJkbGdEdoZH3N7d5cU9MaR2QS4i6ZUkXJKGSGIfQRBXV2K7JOAAK401rq6wXUJP5WGKMkPaLhgRsXIGICqb0iI1BBqgYGFGV-icEM3holnAebgXVP1ReH9PkPbBDCBHhcvRQLGYioMF39NMKqMbLXfxpJ01I7Smk36NCpK8UoQlYjYp4gEGUNndksLb_R7zzQGpPZL2Wk4UbHZ274wvpLFWrboktf5xR8k2T6W-yldj_NgP16Ai9pxAG107EwrC830QuhywTbYerUIwLZeOzB71i82aKcgj1Bgl_GV01pjjYsr2QJBzA"

echo "=========================================="
echo "🧪 FULL BACKEND API TEST WITH TRACING"
echo "=========================================="
echo ""

# Test 1: Health Check
echo "✅ Test 1: Health Check"
curl -s "$BACKEND_URL/health" | python3 -m json.tool
echo -e "\n"

# Test 2: List videos
echo "✅ Test 2: List Videos (with Firebase token)"
curl -s "$BACKEND_URL/list" -H "Authorization: Bearer $FIREBASE_TOKEN" | python3 -m json.tool | head -20
echo -e "\n"

# Test 3: Create small test file
echo "✅ Test 3: Creating Test Video (100KB)"
TEST_FILE="/tmp/test_api_$(date +%s).mp4"
dd if=/dev/zero of="$TEST_FILE" bs=1024 count=100 2>/dev/null
echo "Created: $TEST_FILE"
echo ""

# Test 4: Upload video
echo "✅ Test 4: Upload Video"
UPLOAD_RESPONSE=$(curl -s -X POST "$BACKEND_URL/upload" \
  -H "Authorization: Bearer $FIREBASE_TOKEN" \
  -F "file=@$TEST_FILE")

echo "$UPLOAD_RESPONSE" | python3 -m json.tool
VIDEO_ID=$(echo "$UPLOAD_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('video_id', ''))" 2>/dev/null)
echo ""

if [ -z "$VIDEO_ID" ]; then
  echo "❌ Upload failed!"
  rm -f "$TEST_FILE"
  exit 1
fi

echo "📹 Video ID: $VIDEO_ID"
echo ""

# Test 5: Check database immediately
echo "✅ Test 5: Database Check (Immediate)"
sshpass -p 'P@ssw0rd768' ssh ec2-user@192.168.2.71 \
  "PGPASSWORD='P@ssw0rd768_DB' psql -h localhost -p 5432 -U thakii_user -d thakii_production -c \"SELECT video_id, filename, status, user_email, processed_by_worker, created_at FROM video_tasks WHERE video_id = '$VIDEO_ID';\"" 2>/dev/null
echo ""

# Test 6: Monitor processing
echo "✅ Test 6: Monitor Processing (30 seconds)"
for i in {1..6}; do
  echo "Check $i/6 ($(($i * 5))s):"
  STATUS=$(sshpass -p 'P@ssw0rd768' ssh ec2-user@192.168.2.71 \
    "PGPASSWORD='P@ssw0rd768_DB' psql -h localhost -p 5432 -U thakii_user -d thakii_production -t -c \"SELECT status FROM video_tasks WHERE video_id = '$VIDEO_ID';\"" 2>/dev/null | xargs)
  echo "   Status: $STATUS"
  
  if [ "$STATUS" == "completed" ] || [ "$STATUS" == "failed" ]; then
    echo "   ✅ Processing finished!"
    break
  fi
  sleep 5
done
echo ""

# Test 7: Final status
echo "✅ Test 7: Final Status & Backend Logs"
sshpass -p 'P@ssw0rd768' ssh ec2-user@192.168.2.71 \
  "PGPASSWORD='P@ssw0rd768_DB' psql -h localhost -p 5432 -U thakii_user -d thakii_production -c \"SELECT video_id, status, error_message, processed_by_worker FROM video_tasks WHERE video_id = '$VIDEO_ID';\"" 2>/dev/null
echo ""

# Test 8: Check email logs
echo "✅ Test 8: Email Notification Logs"
sshpass -p 'P@ssw0rd768' ssh ec2-user@192.168.2.71 \
  "cd ~/thakii-backend-api && tail -100 logs/backend.log | grep -E '($VIDEO_ID|Email|Brevo|email)' | tail -20" 2>/dev/null
echo ""

# Test 9: Worker logs
echo "✅ Test 9: Worker Processing Logs"
sshpass -p 'P@ssw0rd768' ssh ec2-user@192.168.2.71 \
  "journalctl -u thakii-worker --since '30 seconds ago' --no-pager | grep '$VIDEO_ID'" 2>/dev/null | head -10
echo ""

# Cleanup
rm -f "$TEST_FILE"

echo "=========================================="
echo "🎉 TEST COMPLETE!"
echo "=========================================="
