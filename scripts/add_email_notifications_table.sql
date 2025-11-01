-- Add email notifications configuration table
-- This stores persistent email notification settings

CREATE TABLE IF NOT EXISTS email_notification_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    config_key VARCHAR(255) UNIQUE NOT NULL,
    config_value TEXT,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert default configuration
INSERT INTO email_notification_config (config_key, config_value, description)
VALUES 
    ('additional_recipients', '[]', 'JSON array of additional email recipients for notifications'),
    ('email_enabled', 'true', 'Whether email notifications are enabled'),
    ('attach_pdf_on_success', 'true', 'Whether to attach PDF files to success notification emails')
ON CONFLICT (config_key) DO NOTHING;

-- Create trigger for auto-updating updated_at
CREATE TRIGGER update_email_notification_config_updated_at 
    BEFORE UPDATE ON email_notification_config
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Grant permissions to thakii_user
GRANT ALL PRIVILEGES ON email_notification_config TO thakii_user;



