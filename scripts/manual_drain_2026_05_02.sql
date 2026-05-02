-- Phase 9: Drain the failed videos backlog (2026-05-02)
-- Requeue all failed videos with attempts reset to 0 so they can be
-- retried with the new persistent-workdir + resumable-transcription pipeline.

BEGIN;

UPDATE video_tasks
SET status = 'in_queue',
    progress_percent = 0,
    error_message = NULL,
    processing_start = NULL,
    processing_started_at = NULL,
    processing_end = NULL,
    assigned_worker_id = NULL,
    assigned_worker = NULL,
    last_heartbeat = NULL,
    assignment_time = NULL,
    processed_by_worker = NULL,
    progress_phase = NULL,
    progress_detail = NULL,
    last_forward_progress_at = NULL,
    attempts = 0,
    last_failure_reason = 'manual drain 2026-05-02 (Stuck-Task Hardening v3 Phase 9)',
    updated_at = CURRENT_TIMESTAMP
WHERE status = 'failed';

COMMIT;
