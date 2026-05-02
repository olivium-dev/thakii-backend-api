# Thakii Operational Runbooks

## 1. Video stuck in `processing` — diagnostic flowchart

```
Is last_heartbeat within the last 30 min?
├── YES → Worker is alive, task is progressing
│   └── Check progress_phase and progress_detail for segment-level progress
│       └── If segments_done is growing → task is healthy, just slow
│       └── If segments_done is flat for >15 min → possible MPS hang
│           └── Check worker subprocess log: <workdir>/<video_id>.pdf.gen.log
│           └── If log size is growing → actively writing (healthy)
│           └── If log size is flat → kill subprocess, task will auto-resume
├── NO → Worker may be dead or restarting
│   └── Is assigned_worker_id == 'worker-thakii-03'?
│       └── SSH to thakii-03 and check: pgrep -fa worker.py
│       └── If no process → restart: launchctl kickstart user/501/com.thakii.worker
│       └── If process exists → check heartbeat endpoint: curl localhost:8080/health
```

### Quick fix commands:
```bash
# Requeue a specific stuck video via admin API
curl -X POST https://thakii-02.fanusdigital.site/thakii-be/admin/videos/{VIDEO_ID}/requeue \
  -H "Authorization: Bearer $TOKEN"

# Requeue ALL stuck videos
curl -X POST https://thakii-02.fanusdigital.site/thakii-be/admin/videos/requeue-stuck \
  -H "Authorization: Bearer $TOKEN"

# Check timeline for a specific video
curl https://thakii-02.fanusdigital.site/thakii-be/admin/videos/{VIDEO_ID}/timeline \
  -H "Authorization: Bearer $TOKEN"
```

## 2. Worker not picking up tasks

```
1. Verify worker process is running:
   ssh thakii-03 'pgrep -fa worker.py'

2. Check worker logs:
   ssh thakii-03 'tail -50 /Users/fanusdigital/thakii-worker-service/logs/worker.log'

3. Check disk space:
   ssh thakii-03 'df -h /'
   → If < MIN_FREE_GB_TO_PICKUP (3 GB), worker refuses pickups

4. Check queue has items:
   psql -c "SELECT count(*) FROM video_tasks WHERE status = 'in_queue'"

5. Check if worker API is enabled:
   curl http://localhost:5001/health  (backend)
   → Verify Worker:EnableWorkerApi = true

6. Check internal secret match:
   Verify INTERNAL_WORKER_SECRET matches on both worker and backend
```

## 3. Backlog growing — queue not draining

```
1. Check current processing count:
   psql -c "SELECT status, count(*) FROM video_tasks GROUP BY status"

2. If processing = 0 but in_queue > 0:
   → Worker is dead or not polling. See Runbook #2.

3. If processing = MAX_CONCURRENT_TASKS:
   → Worker is at capacity. Check if current tasks are making progress.
   → Check progress_detail for forward movement.

4. If many failed tasks are clogging:
   → Check last_failure_reason for common patterns
   → Requeue with: UPDATE video_tasks SET status='in_queue', attempts=0
     WHERE status='failed' AND last_failure_reason LIKE '%timeout%';

5. Monitor SLO:
   curl https://thakii-02.fanusdigital.site/thakii-be/admin/metrics/stuck-tasks \
     -H "Authorization: Bearer $TOKEN"
```

## 4. Manual workdir cleanup

```bash
# On thakii-03:
WDBASE=/Users/fanusdigital/thakii-worker-service/workdir

# List all workdirs with their ages and lock status:
for d in $WDBASE/*/; do
  age=$(python3 -c "import os,time; print(int((time.time()-os.path.getmtime('$d'))/3600))")
  locked=$([ -f "${d}lock.json" ] && echo "LOCKED" || echo "unlocked")
  echo "$d  age=${age}h  $locked"
done

# Prune unlocked workdirs older than 24 hours:
find $WDBASE -mindepth 1 -maxdepth 1 -type d -mmin +1440 | while read d; do
  [ -f "$d/lock.json" ] && continue
  echo "Removing: $d"
  rm -rf "$d"
done
```

## 5. Long-video opt-in flow

Videos > 2 hours (7200s) are accepted by default (enforced limit is in
`TASK_TIMEOUT_SECONDS` at the worker level). The backend stores
`video_duration_seconds` and computes an adaptive timeout hint clamped
to [900, 14400]s.

If a very long video keeps timing out:
1. Check its `video_duration_seconds` via the timeline endpoint
2. Verify the adaptive timeout hint is reasonable
3. If needed, temporarily bump `TASK_TIMEOUT_SECONDS` on the worker
4. Long-term: Phase 5 resumable transcription means even after a timeout,
   the next attempt resumes from the last checkpoint

## Appendix: Key configuration values

| Setting | Location | Default | Purpose |
|---------|----------|---------|---------|
| TASK_TIMEOUT_SECONDS | worker .env | 18000 (5h) | Hard per-task timeout ceiling |
| Reaper:HeartbeatStaleSeconds | appsettings.json | 1800 (30m) | Heartbeat considered stale after |
| Reaper:NoForwardProgressSeconds | appsettings.json | 900 (15m) | Forward progress considered stale after |
| Reaper:HardCeilingSeconds | appsettings.json | 14400 (4h) | Absolute maximum processing time |
| Reaper:MaxAttempts | appsettings.json | 3 | Max retries before marking failed |
| MIN_FREE_GB_TO_PICKUP | worker .env | 3 | Minimum free disk to accept tasks |
| WORKDIR_RETENTION_HOURS | worker .env | 24 | Hours to keep completed workdirs |
| MAX_VIDEO_SIZE_GB | worker .env | 20 | Reject downloads larger than this |
