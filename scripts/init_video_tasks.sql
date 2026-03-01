-- Run this once after creating the database.
-- 1) Create database:  createdb -U postgres thakii_production
-- 2) Run this file:    psql -U postgres -d thakii_production -f scripts/init_video_tasks.sql

-- ============================================================================
-- VIDEO TASKS TABLE
-- ============================================================================

DROP TABLE IF EXISTS batch_import_videos CASCADE;
DROP TABLE IF EXISTS batch_import_jobs CASCADE;
DROP TABLE IF EXISTS video_tasks CASCADE;

CREATE TABLE video_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    video_id VARCHAR(255) UNIQUE NOT NULL,
    filename VARCHAR(500) NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    user_email VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL,
    upload_date TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    s3_key VARCHAR(500),
    pdf_url TEXT,
    error_message TEXT,
    processing_start TIMESTAMP,
    processing_end TIMESTAMP,
    cancelled BOOLEAN DEFAULT FALSE,
    cancelled_at TIMESTAMP,
    cancelled_by VARCHAR(255),
    cancellation_reason TEXT,
    cancellation_requested BOOLEAN DEFAULT FALSE,
    cancellation_requested_at TIMESTAMP,
    progress_percent INTEGER DEFAULT 0
);

CREATE INDEX idx_video_tasks_user_id ON video_tasks(user_id);
CREATE INDEX idx_video_tasks_status ON video_tasks(status);
CREATE INDEX idx_video_tasks_created_at ON video_tasks(created_at DESC);

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_video_tasks_updated_at
    BEFORE UPDATE ON video_tasks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE OR REPLACE FUNCTION cancel_video_task(
    p_video_id VARCHAR(255),
    p_cancelled_by VARCHAR(255),
    p_reason TEXT DEFAULT 'User requested cancellation'
)
RETURNS BOOLEAN AS $$
DECLARE
    v_current_status VARCHAR(50);
    v_result BOOLEAN := FALSE;
BEGIN
    SELECT status INTO v_current_status FROM video_tasks WHERE video_id = p_video_id;
    IF v_current_status IS NULL THEN
        RETURN FALSE;
    END IF;

    IF v_current_status IN ('in_queue', 'uploaded') THEN
        UPDATE video_tasks
        SET status = 'cancelled', cancelled = TRUE, cancelled_at = CURRENT_TIMESTAMP,
            cancelled_by = p_cancelled_by, cancellation_reason = p_reason, updated_at = CURRENT_TIMESTAMP
        WHERE video_id = p_video_id;
        v_result := TRUE;
    ELSIF v_current_status = 'processing' THEN
        UPDATE video_tasks
        SET cancellation_requested = TRUE, cancellation_requested_at = CURRENT_TIMESTAMP,
            cancelled_by = p_cancelled_by, cancellation_reason = p_reason, status = 'cancelling', updated_at = CURRENT_TIMESTAMP
        WHERE video_id = p_video_id;
        v_result := TRUE;
    ELSIF v_current_status IN ('done', 'completed', 'failed') THEN
        UPDATE video_tasks
        SET cancelled = TRUE, cancelled_at = CURRENT_TIMESTAMP, cancelled_by = p_cancelled_by,
            cancellation_reason = p_reason, updated_at = CURRENT_TIMESTAMP
        WHERE video_id = p_video_id;
        v_result := TRUE;
    END IF;
    RETURN v_result;
END;
$$ LANGUAGE plpgsql;

-- Function used by worker API to check cancellation
CREATE OR REPLACE FUNCTION is_cancellation_requested(p_video_id VARCHAR(255))
RETURNS BOOLEAN AS $$
DECLARE
    v_result BOOLEAN;
BEGIN
    SELECT COALESCE(cancellation_requested, FALSE) INTO v_result
    FROM video_tasks WHERE video_id = p_video_id;
    RETURN COALESCE(v_result, FALSE);
END;
$$ LANGUAGE plpgsql;

-- Function used by worker API to complete cancellation
CREATE OR REPLACE FUNCTION complete_cancellation(p_video_id VARCHAR(255))
RETURNS VOID AS $$
BEGIN
    UPDATE video_tasks
    SET status = 'cancelled', cancelled = TRUE, cancelled_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
    WHERE video_id = p_video_id;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- BATCH IMPORT TABLES
-- ============================================================================

CREATE TABLE batch_import_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id VARCHAR(255) UNIQUE NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    user_email VARCHAR(255) NOT NULL,
    share_url TEXT NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    total_videos INTEGER DEFAULT 0,
    processed_videos INTEGER DEFAULT 0,
    failed_videos INTEGER DEFAULT 0,
    total_size BIGINT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT
);

CREATE INDEX idx_batch_import_jobs_user_id ON batch_import_jobs(user_id);
CREATE INDEX idx_batch_import_jobs_status ON batch_import_jobs(status);

CREATE TABLE batch_import_videos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id VARCHAR(255) NOT NULL REFERENCES batch_import_jobs(job_id),
    video_name VARCHAR(500) NOT NULL,
    video_id VARCHAR(255),
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    progress_percent INTEGER DEFAULT 0,
    error_message TEXT,
    file_size BIGINT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_batch_import_videos_job_id ON batch_import_videos(job_id);
