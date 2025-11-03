-- Add worker assignment columns to video_tasks table
-- This enables the new worker API architecture with proper task assignment

-- Add columns for worker assignment tracking
ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS assigned_worker VARCHAR(100);
ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS assignment_time TIMESTAMP;
ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS last_heartbeat TIMESTAMP;

-- Add index for efficient task pickup
CREATE INDEX IF NOT EXISTS idx_task_pickup 
ON video_tasks(status, created_at) 
WHERE status IN ('in_queue', 'uploaded');

-- Add index for worker assignment queries
CREATE INDEX IF NOT EXISTS idx_worker_assignment
ON video_tasks(assigned_worker, status)
WHERE assigned_worker IS NOT NULL;
