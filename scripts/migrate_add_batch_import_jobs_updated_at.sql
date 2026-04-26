-- ============================================================================
-- Migration: add updated_at column + trigger on batch_import_jobs
-- ============================================================================
--
-- Background:
--   Production had a BEFORE-UPDATE trigger
--     update_batch_import_jobs_updated_at -> update_updated_at_column()
--   that assigned NEW.updated_at = NOW(), but batch_import_jobs had no
--   updated_at column. Every UPDATE on the table failed with:
--     42703: record "new" has no field "updated_at"
--   This silently broke BatchImportService.ProcessBatchJobAsync (which
--   transitions jobs through pending -> processing -> completed) and made
--   newly-submitted batch import jobs appear "stuck" in the UI.
--
-- Fix:
--   1. Add the missing updated_at column (idempotent).
--   2. Re-create the trigger so it exists in environments that never had it
--      (also idempotent via DROP IF EXISTS / CREATE).
--
-- Safe to re-run; idempotent.
-- ============================================================================

ALTER TABLE batch_import_jobs
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

DROP TRIGGER IF EXISTS update_batch_import_jobs_updated_at ON batch_import_jobs;

CREATE TRIGGER update_batch_import_jobs_updated_at
    BEFORE UPDATE ON batch_import_jobs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
