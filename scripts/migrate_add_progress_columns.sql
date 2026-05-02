-- Phase 3 of Stuck-Task Hardening v3: Fine-grained progress tracking
-- Adds columns for the worker to report segment-level progress so the
-- reaper can distinguish "actively transcribing" from "truly stuck".

ALTER TABLE video_tasks
    ADD COLUMN IF NOT EXISTS progress_phase           VARCHAR(32),
    ADD COLUMN IF NOT EXISTS progress_detail          JSONB,
    ADD COLUMN IF NOT EXISTS last_forward_progress_at TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_video_tasks_forward_progress
    ON video_tasks(last_forward_progress_at) WHERE status = 'processing';
