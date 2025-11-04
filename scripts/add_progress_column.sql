-- Add progress_percent column to video_tasks table
-- This allows storing and displaying video processing progress

-- Add progress_percent column
ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS progress_percent INTEGER DEFAULT 0;

-- Add index for performance
CREATE INDEX IF NOT EXISTS idx_video_tasks_progress ON video_tasks(progress_percent);

-- Comment the column
COMMENT ON COLUMN video_tasks.progress_percent IS 'Processing progress percentage (0-100)';

-- Verify column was added
SELECT 'Progress column added successfully' as status;
SELECT column_name, data_type, column_default FROM information_schema.columns 
WHERE table_name = 'video_tasks' AND column_name = 'progress_percent';
