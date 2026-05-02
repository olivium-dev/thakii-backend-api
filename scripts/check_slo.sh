#!/usr/bin/env bash
# Phase 10: SLO check script — run via cron every 5 minutes.
# Queries the admin metrics endpoint and alerts if SLOs are breached.
#
# Usage: THAKII_TOKEN=<admin_token> ./check_slo.sh
# Cron:  */5 * * * * THAKII_TOKEN=xxx /path/to/check_slo.sh >> /var/log/thakii_slo.log 2>&1

set -euo pipefail

API_BASE="${THAKII_API_BASE:-https://thakii-02.fanusdigital.site/thakii-be}"
TOKEN="${THAKII_TOKEN:?THAKII_TOKEN env var is required}"

metrics=$(curl -sf -H "Authorization: Bearer $TOKEN" "$API_BASE/admin/metrics/stuck-tasks" 2>/dev/null || echo "{}")

no_hb=$(echo "$metrics" | python3 -c "import sys,json; print(json.load(sys.stdin).get('processing_no_heartbeat_5m',0))" 2>/dev/null || echo 0)
queue_old=$(echo "$metrics" | python3 -c "import sys,json; print(json.load(sys.stdin).get('in_queue_older_30m',0))" 2>/dev/null || echo 0)
processing=$(echo "$metrics" | python3 -c "import sys,json; print(json.load(sys.stdin).get('processing_total',0))" 2>/dev/null || echo 0)
in_queue=$(echo "$metrics" | python3 -c "import sys,json; print(json.load(sys.stdin).get('in_queue_total',0))" 2>/dev/null || echo 0)

BREACHED=0
NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

if [ "$no_hb" -gt 0 ]; then
  echo "[$NOW] SLO BREACH: $no_hb processing tasks with no heartbeat for >5m"
  BREACHED=1
fi

if [ "$queue_old" -gt 5 ]; then
  echo "[$NOW] SLO BREACH: $queue_old tasks in queue for >30m (S3: p95 <= 30m)"
  BREACHED=1
fi

if [ "$BREACHED" -eq 0 ]; then
  echo "[$NOW] SLO OK: processing=$processing, in_queue=$in_queue, stale_hb=$no_hb, queue_old=$queue_old"
fi

exit $BREACHED
