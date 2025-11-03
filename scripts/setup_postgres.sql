-- PostgreSQL Database Schema for Thakii Lecture2PDF Service
-- Replaces Firebase Firestore with PostgreSQL

-- Drop existing tables if they exist (for clean setup)
DROP TABLE IF EXISTS batch_import_videos CASCADE;
DROP TABLE IF EXISTS batch_import_jobs CASCADE;
DROP TABLE IF EXISTS notifications CASCADE;
DROP TABLE IF EXISTS processing_servers CASCADE;
DROP TABLE IF EXISTS admin_users CASCADE;
DROP TABLE IF EXISTS video_tasks CASCADE;

-- video_tasks table (replaces Firestore collection)
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
    processing_end TIMESTAMP
);

-- admin_users table
CREATE TABLE admin_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    role VARCHAR(50) NOT NULL,
    status VARCHAR(50) NOT NULL,
    is_super_admin BOOLEAN DEFAULT FALSE,
    description TEXT,
    added_by VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- processing_servers table
CREATE TABLE processing_servers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) UNIQUE NOT NULL,
    url VARCHAR(500) NOT NULL,
    type VARCHAR(50) NOT NULL,
    status VARCHAR(50) NOT NULL,
    description TEXT,
    health_status JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_health_check TIMESTAMP
);

-- notifications table
CREATE TABLE notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255),
    title VARCHAR(255) NOT NULL,
    body TEXT NOT NULL,
    data JSONB,
    type VARCHAR(50) NOT NULL,
    read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- batch_import_jobs table
CREATE TABLE batch_import_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL,
    user_email VARCHAR(255) NOT NULL,
    share_url TEXT NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    total_videos INTEGER DEFAULT 0,
    processed_videos INTEGER DEFAULT 0,
    failed_videos INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT
);

-- batch_import_videos table
CREATE TABLE batch_import_videos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_job_id UUID REFERENCES batch_import_jobs(id) ON DELETE CASCADE,
    video_name VARCHAR(500) NOT NULL,
    video_size BIGINT,
    download_url TEXT NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'queued',
    video_id UUID,
    s3_key VARCHAR(500),
    progress_percent INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    download_started_at TIMESTAMP,
    download_completed_at TIMESTAMP
);

-- Create indexes for performance
CREATE INDEX idx_video_tasks_user_id ON video_tasks(user_id);
CREATE INDEX idx_video_tasks_status ON video_tasks(status);
CREATE INDEX idx_video_tasks_created_at ON video_tasks(created_at DESC);
CREATE INDEX idx_admin_users_email ON admin_users(email);
CREATE INDEX idx_notifications_user_id ON notifications(user_id);
CREATE INDEX idx_notifications_created_at ON notifications(created_at DESC);
CREATE INDEX idx_processing_servers_status ON processing_servers(status);
CREATE INDEX idx_batch_jobs_user_status ON batch_import_jobs(user_id, status);
CREATE INDEX idx_batch_videos_job_status ON batch_import_videos(batch_job_id, status);
CREATE INDEX idx_batch_videos_status ON batch_import_videos(status);

-- Create trigger function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create triggers for auto-updating updated_at
CREATE TRIGGER update_video_tasks_updated_at BEFORE UPDATE ON video_tasks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_admin_users_updated_at BEFORE UPDATE ON admin_users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_processing_servers_updated_at BEFORE UPDATE ON processing_servers
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_batch_import_jobs_updated_at BEFORE UPDATE ON batch_import_jobs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_batch_import_videos_updated_at BEFORE UPDATE ON batch_import_videos
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Insert default super admins
INSERT INTO admin_users (email, role, status, is_super_admin, description, added_by)
VALUES 
    ('ouday.khaled@gmail.com', 'super_admin', 'active', TRUE, 'System Super Admin', 'system'),
    ('appsaawt@gmail.com', 'super_admin', 'active', TRUE, 'System Super Admin', 'system')
ON CONFLICT (email) DO NOTHING;

-- Grant permissions to thakii_user
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO thakii_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO thakii_user;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO thakii_user;




