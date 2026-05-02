-- Phase 8 of Stuck-Task Hardening v3: Per-stage timing columns
-- Allows "where is the time going?" queries without SSH.

ALTER TABLE video_tasks
    ADD COLUMN IF NOT EXISTS download_seconds   INTEGER,
    ADD COLUMN IF NOT EXISTS audio_seconds      INTEGER,
    ADD COLUMN IF NOT EXISTS frames_seconds     INTEGER,
    ADD COLUMN IF NOT EXISTS transcribe_seconds INTEGER,
    ADD COLUMN IF NOT EXISTS pdf_seconds        INTEGER,
    ADD COLUMN IF NOT EXISTS upload_seconds     INTEGER;
