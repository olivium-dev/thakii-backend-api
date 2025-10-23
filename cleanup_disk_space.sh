#!/bin/bash
set -e

echo "🧹 EMERGENCY DISK CLEANUP"
echo "========================="

echo "Before cleanup:"
df -h

echo ""
echo "Cleaning /tmp directory..."

# Clean up failed backup attempts
sudo find /tmp -maxdepth 1 -name "backend-backup-*" -type d -exec rm -rf {} + 2>/dev/null || true
echo "✅ Removed backup directories"

# Clean up old video files
sudo find /tmp -name "*.mp4" -type f -mtime +0 -delete 2>/dev/null || true
sudo find /tmp -name "*.pdf" -type f -mtime +0 -delete 2>/dev/null || true
echo "✅ Removed old video/PDF files"

# Clean up worker temp files
sudo rm -rf /tmp/thakii-worker/* 2>/dev/null || true
sudo rm -rf /tmp/tmp* 2>/dev/null || true
echo "✅ Removed worker temp files"

# Clean up any other large temp files
sudo find /tmp -type f -size +10M -mtime +0 -delete 2>/dev/null || true
echo "✅ Removed large temp files"

echo ""
echo "After cleanup:"
df -h

echo ""
echo "🎉 Disk cleanup complete!"
