-- Adds the columns and indexes required by the StaleTaskReaperService
-- (Phase B4 of the Stuck Task Pipeline Hardening rollout) and by the
-- worker liveness tracking changes in PickupTaskAsync / heartbeat path.
--
-- Idempotent: every statement uses IF NOT EXISTS so it can be re-run
-- safely on environments where some columns were already present.
-- Safe online: ALTER TABLE ADD COLUMN with DEFAULT is metadata-only on
-- PostgreSQL >= 11, and CREATE INDEX uses partial indexes scoped to
-- 'processing' rows only.

BEGIN;

-- Worker liveness columns (these exist on production but not in the
-- checked-in init script; we re-declare them defensively).
ALTER TABLE video_tasks
    ADD COLUMN IF NOT EXISTS assigned_worker_id   VARCHAR(255),
    ADD COLUMN IF NOT EXISTS assigned_worker      VARCHAR(255),
    ADD COLUMN IF NOT EXISTS processing_started_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS last_heartbeat       TIMESTAMP,
    ADD COLUMN IF NOT EXISTS assignment_time      TIMESTAMP,
    ADD COLUMN IF NOT EXISTS processed_by_worker  VARCHAR(255);

-- Reaper / retry bookkeeping.
ALTER TABLE video_tasks
    ADD COLUMN IF NOT EXISTS attempts             INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_failure_reason  TEXT;

-- Partial indexes for the reaper sweep. They only cover 'processing'
-- rows so they stay tiny under normal load.
CREATE INDEX IF NOT EXISTS idx_video_tasks_processing_heartbeat
    ON video_tasks(last_heartbeat)
    WHERE status = 'processing';

CREATE INDEX IF NOT EXISTS idx_video_tasks_processing_start
    ON video_tasks(processing_start)
    WHERE status = 'processing';

CREATE INDEX IF NOT EXISTS idx_video_tasks_assigned_worker
    ON video_tasks(assigned_worker_id)
    WHERE status = 'processing';

COMMIT;
