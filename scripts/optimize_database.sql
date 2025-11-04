-- Performance optimization indexes for Thakii system
-- Run with: PGPASSWORD=P@ssw0rd768_DB psql -h localhost -U thakii_user -d thakii_production -f optimize_database.sql
-- These indexes are created CONCURRENTLY to avoid blocking production queries

-- Index for faster task pickup (WHERE status IN queue)
-- This dramatically speeds up the worker pickup query
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_queue_pickup 
ON video_tasks(status, created_at) 
WHERE status IN ('in_queue', 'uploaded');

-- Index for heartbeat queries
-- Speeds up heartbeat updates and stale task detection
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_worker_heartbeat 
ON video_tasks(assigned_worker, last_heartbeat)
WHERE status = 'processing';

-- Index for worker task queries
-- Improves worker status checks and task assignment queries
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_worker_status 
ON video_tasks(assigned_worker, status);

-- Index for batch import lookups
-- Speeds up batch import status queries
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_batch_video_status
ON batch_import_videos(status, created_at)
WHERE status IN ('queued', 'downloading');

-- Analyze tables for query planner optimization
ANALYZE video_tasks;
ANALYZE batch_import_videos;

-- Show index creation results
SELECT 
    schemaname,
    tablename,
    indexname,
    idx_scan as index_scans,
    idx_tup_read as tuples_read,
    idx_tup_fetch as tuples_fetched
FROM pg_stat_user_indexes
WHERE schemaname = 'public'
  AND tablename IN ('video_tasks', 'batch_import_videos')
ORDER BY tablename, idx_scan DESC;

-- Verify indexes were created
SELECT 
    indexname,
    indexdef
FROM pg_indexes
WHERE tablename IN ('video_tasks', 'batch_import_videos')
  AND indexname LIKE 'idx_%'
ORDER BY indexname;
