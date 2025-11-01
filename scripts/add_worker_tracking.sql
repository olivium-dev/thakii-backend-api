-- Migration: Add worker tracking to video_tasks table
-- This allows tracking which worker (primary/fallback) processed each video

-- Add processed_by_worker column to track which worker handled the video
ALTER TABLE video_tasks 
ADD COLUMN IF NOT EXISTS processed_by_worker VARCHAR(50);

-- Add processed_by_worker_url column to track the worker URL
ALTER TABLE video_tasks 
ADD COLUMN IF NOT EXISTS processed_by_worker_url VARCHAR(500);

-- Add worker_attempts column to track retry attempts
ALTER TABLE video_tasks 
ADD COLUMN IF NOT EXISTS worker_attempts INTEGER DEFAULT 0;

-- Add index for querying by worker
CREATE INDEX IF NOT EXISTS idx_video_tasks_processed_by_worker 
ON video_tasks(processed_by_worker);

-- Comment the columns
COMMENT ON COLUMN video_tasks.processed_by_worker IS 'Which worker processed this video: primary, fallback, or none';
COMMENT ON COLUMN video_tasks.processed_by_worker_url IS 'Full URL of the worker that processed this video';
COMMENT ON COLUMN video_tasks.worker_attempts IS 'Number of worker trigger attempts';

-- Display migration status
SELECT 
    column_name, 
    data_type, 
    is_nullable
FROM information_schema.columns 
WHERE table_name = 'video_tasks' 
AND column_name IN ('processed_by_worker', 'processed_by_worker_url', 'worker_attempts')
ORDER BY column_name;





