-- Phase 2 of Stuck-Task Hardening v3: Adaptive timeout
-- Adds video_duration_seconds so PickupTaskAsync can compute a per-task timeout hint.

ALTER TABLE video_tasks
    ADD COLUMN IF NOT EXISTS video_duration_seconds INTEGER;

CREATE INDEX IF NOT EXISTS idx_video_tasks_duration
    ON video_tasks(video_duration_seconds);
