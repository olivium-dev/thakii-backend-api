-- Safe Batch Import Tables Creation
-- Creates batch import tables WITHOUT dropping existing video_tasks
-- This is a SAFE migration that preserves existing data

-- Create batch_import_jobs table if it doesn't exist
CREATE TABLE IF NOT EXISTS batch_import_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL,
    user_email VARCHAR(255) NOT NULL,
    share_url TEXT NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending', -- pending, processing, completed, failed
    total_videos INTEGER DEFAULT 0,
    processed_videos INTEGER DEFAULT 0,
    failed_videos INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT
);

-- Create batch_import_videos table if it doesn't exist
CREATE TABLE IF NOT EXISTS batch_import_videos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_job_id UUID REFERENCES batch_import_jobs(id) ON DELETE CASCADE,
    video_name VARCHAR(500) NOT NULL,
    video_size BIGINT,
    download_url TEXT NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'queued', -- queued, downloading, uploading, completed, failed
    video_id UUID, -- Links to video_tasks.video_id when created
    s3_key VARCHAR(500),
    progress_percent INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    download_started_at TIMESTAMP,
    download_completed_at TIMESTAMP
);

-- Create indexes for performance (only if they don't exist)
CREATE INDEX IF NOT EXISTS idx_batch_jobs_user_status ON batch_import_jobs(user_id, status);
CREATE INDEX IF NOT EXISTS idx_batch_videos_job_status ON batch_import_videos(batch_job_id, status);
CREATE INDEX IF NOT EXISTS idx_batch_videos_status ON batch_import_videos(status);

-- Create function for updating updated_at column if it doesn't exist
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create triggers for auto-updating updated_at (safe - will replace if exists)
DROP TRIGGER IF EXISTS update_batch_import_jobs_updated_at ON batch_import_jobs;
CREATE TRIGGER update_batch_import_jobs_updated_at 
    BEFORE UPDATE ON batch_import_jobs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_batch_import_videos_updated_at ON batch_import_videos;
CREATE TRIGGER update_batch_import_videos_updated_at 
    BEFORE UPDATE ON batch_import_videos
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Ensure video_tasks table has required columns (safe ALTER TABLE)
-- These will only add columns if they don't exist
ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS processed_by_worker VARCHAR(50);
ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS processing_started_at TIMESTAMP;
ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS assigned_worker_id VARCHAR(100);

-- Create indexes for video_tasks if they don't exist
CREATE INDEX IF NOT EXISTS idx_video_tasks_processed_by_worker ON video_tasks(processed_by_worker);
CREATE INDEX IF NOT EXISTS idx_video_tasks_assigned_worker ON video_tasks(assigned_worker_id);
CREATE INDEX IF NOT EXISTS idx_video_tasks_status ON video_tasks(status);
CREATE INDEX IF NOT EXISTS idx_video_tasks_user_id ON video_tasks(user_id);

SELECT 'Safe batch import tables and columns created successfully' as result;
