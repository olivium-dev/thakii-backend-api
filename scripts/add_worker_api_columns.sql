-- Worker API Database Migration
-- Adds missing columns for Worker API functionality

-- Add Worker API columns to video_tasks table (matching worker_task_manager.py expectations)
ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS processed_by_worker VARCHAR(50);
ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS processing_started_at TIMESTAMP;
ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS assigned_worker_id VARCHAR(100);

-- Add columns that worker_task_manager.py actually uses
ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS assigned_worker VARCHAR(100);
ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS last_heartbeat TIMESTAMP;
ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS assignment_time TIMESTAMP;
ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS processing_start TIMESTAMP;

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_video_tasks_processed_by_worker ON video_tasks(processed_by_worker);
CREATE INDEX IF NOT EXISTS idx_video_tasks_assigned_worker_id ON video_tasks(assigned_worker_id);
CREATE INDEX IF NOT EXISTS idx_video_tasks_assigned_worker ON video_tasks(assigned_worker);
CREATE INDEX IF NOT EXISTS idx_video_tasks_last_heartbeat ON video_tasks(last_heartbeat);

-- Verify columns were added
SELECT 'Worker API columns added successfully' as status;
SELECT column_name, data_type FROM information_schema.columns 
WHERE table_name = 'video_tasks' AND column_name IN ('processed_by_worker', 'processing_started_at', 'assigned_worker_id');
