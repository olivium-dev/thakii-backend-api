-- Video Cancellation Feature Database Migration
-- Adds columns to support clean video cancellation at any stage

-- Add cancellation-related columns to video_tasks table
ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS cancelled BOOLEAN DEFAULT FALSE;
ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMP;
ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS cancelled_by VARCHAR(255);
ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS cancellation_reason TEXT;

-- Add a cancellation_requested flag for worker to check
ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS cancellation_requested BOOLEAN DEFAULT FALSE;
ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS cancellation_requested_at TIMESTAMP;

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_video_tasks_cancelled 
    ON video_tasks(cancelled) 
    WHERE cancelled = TRUE;

CREATE INDEX IF NOT EXISTS idx_video_tasks_cancellation_requested 
    ON video_tasks(cancellation_requested) 
    WHERE cancellation_requested = TRUE;

-- Create composite index for finding active cancellation requests
CREATE INDEX IF NOT EXISTS idx_video_tasks_active_cancellations 
    ON video_tasks(status, cancellation_requested) 
    WHERE cancellation_requested = TRUE AND status IN ('processing', 'in_queue');

-- Add constraint to ensure cancelled videos have a cancelled_at timestamp
ALTER TABLE video_tasks ADD CONSTRAINT IF NOT EXISTS check_cancelled_timestamp 
    CHECK (cancelled = FALSE OR cancelled_at IS NOT NULL);

-- Add new status value 'cancelled' to the status column documentation
COMMENT ON COLUMN video_tasks.status IS 'Valid values: in_queue, uploaded, processing, done, completed, failed, cancelled, cancelling';

-- Create a view for cancelled videos for easy monitoring
CREATE OR REPLACE VIEW cancelled_videos AS
SELECT 
    video_id,
    filename,
    user_id,
    user_email,
    status,
    cancelled,
    cancelled_at,
    cancelled_by,
    cancellation_reason,
    created_at,
    updated_at
FROM video_tasks
WHERE cancelled = TRUE
ORDER BY cancelled_at DESC;

-- Create a function to handle cancellation logic
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
    -- Get current status
    SELECT status INTO v_current_status
    FROM video_tasks
    WHERE video_id = p_video_id;
    
    IF v_current_status IS NULL THEN
        RETURN FALSE; -- Video not found
    END IF;
    
    -- Update based on current status
    IF v_current_status IN ('in_queue', 'uploaded') THEN
        -- Immediate cancellation for queued videos
        UPDATE video_tasks
        SET 
            status = 'cancelled',
            cancelled = TRUE,
            cancelled_at = CURRENT_TIMESTAMP,
            cancelled_by = p_cancelled_by,
            cancellation_reason = p_reason,
            updated_at = CURRENT_TIMESTAMP
        WHERE video_id = p_video_id;
        v_result := TRUE;
        
    ELSIF v_current_status = 'processing' THEN
        -- Request cancellation for processing videos
        UPDATE video_tasks
        SET 
            cancellation_requested = TRUE,
            cancellation_requested_at = CURRENT_TIMESTAMP,
            cancelled_by = p_cancelled_by,
            cancellation_reason = p_reason,
            status = 'cancelling',
            updated_at = CURRENT_TIMESTAMP
        WHERE video_id = p_video_id;
        v_result := TRUE;
        
    ELSIF v_current_status IN ('done', 'completed', 'failed') THEN
        -- Mark as cancelled but keep the status for history
        UPDATE video_tasks
        SET 
            cancelled = TRUE,
            cancelled_at = CURRENT_TIMESTAMP,
            cancelled_by = p_cancelled_by,
            cancellation_reason = p_reason,
            updated_at = CURRENT_TIMESTAMP
        WHERE video_id = p_video_id;
        v_result := TRUE;
        
    END IF;
    
    RETURN v_result;
END;
$$ LANGUAGE plpgsql;

-- Create a function for workers to check if cancellation is requested
CREATE OR REPLACE FUNCTION is_cancellation_requested(p_video_id VARCHAR(255))
RETURNS BOOLEAN AS $$
DECLARE
    v_cancellation_requested BOOLEAN;
BEGIN
    SELECT cancellation_requested INTO v_cancellation_requested
    FROM video_tasks
    WHERE video_id = p_video_id;
    
    RETURN COALESCE(v_cancellation_requested, FALSE);
END;
$$ LANGUAGE plpgsql;

-- Create a function to complete cancellation (called by worker)
CREATE OR REPLACE FUNCTION complete_cancellation(p_video_id VARCHAR(255))
RETURNS VOID AS $$
BEGIN
    UPDATE video_tasks
    SET 
        status = 'cancelled',
        cancelled = TRUE,
        cancelled_at = COALESCE(cancelled_at, CURRENT_TIMESTAMP),
        cancellation_requested = FALSE,
        updated_at = CURRENT_TIMESTAMP
    WHERE video_id = p_video_id
    AND cancellation_requested = TRUE;
END;
$$ LANGUAGE plpgsql;

-- Grant permissions to thakii_user
GRANT EXECUTE ON FUNCTION cancel_video_task TO thakii_user;
GRANT EXECUTE ON FUNCTION is_cancellation_requested TO thakii_user;
GRANT EXECUTE ON FUNCTION complete_cancellation TO thakii_user;
GRANT SELECT ON cancelled_videos TO thakii_user;

-- Verify the migration
SELECT 
    'Cancellation columns added successfully' as status,
    COUNT(*) FILTER (WHERE column_name = 'cancelled') as cancelled_col,
    COUNT(*) FILTER (WHERE column_name = 'cancelled_at') as cancelled_at_col,
    COUNT(*) FILTER (WHERE column_name = 'cancelled_by') as cancelled_by_col,
    COUNT(*) FILTER (WHERE column_name = 'cancellation_reason') as reason_col,
    COUNT(*) FILTER (WHERE column_name = 'cancellation_requested') as request_col
FROM information_schema.columns 
WHERE table_name = 'video_tasks' 
AND column_name IN ('cancelled', 'cancelled_at', 'cancelled_by', 'cancellation_reason', 'cancellation_requested');
