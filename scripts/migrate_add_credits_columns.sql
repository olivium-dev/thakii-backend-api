-- Migration: add credits_charged, credits_refunded, refund_reason to video_tasks
-- Run on existing DBs that were created before these columns existed:
--   psql -U postgres -d thakii_production -f scripts/migrate_add_credits_columns.sql
-- Safe to run multiple times (IF NOT EXISTS avoids errors if columns already exist).

ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS credits_charged NUMERIC(18,4) DEFAULT 0;
ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS credits_refunded BOOLEAN DEFAULT FALSE;
ALTER TABLE video_tasks ADD COLUMN IF NOT EXISTS refund_reason TEXT;
