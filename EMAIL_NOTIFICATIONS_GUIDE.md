# 📧 Email Notifications Guide

## Overview

The Thakii Backend API now supports automatic email notifications when video processing completes (success or failure). This feature includes:

1. **Automatic Summary Emails**: Sent when video processing finishes
2. **PDF Attachments**: PDFs are attached to success notification emails
3. **Multiple Recipients**: Support for additional notification recipients
4. **Admin Management**: API endpoints to configure email settings

---

## 🚀 Quick Setup

### 1. Configure SMTP Settings

Add these environment variables to your `.env` file:

```bash
# Required SMTP Configuration
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-app-password

# Optional Sender Configuration
FROM_EMAIL=your-email@gmail.com
FROM_NAME=Thakii Lecture2PDF

# Optional Additional Recipients (comma-separated)
NOTIFICATION_EMAILS=admin@yourcompany.com,notifications@yourcompany.com
```

### 2. Gmail Setup (Recommended)

1. Enable 2-Factor Authentication on your Gmail account
2. Generate an App Password: https://myaccount.google.com/apppasswords
3. Use the App Password as `SMTP_PASSWORD` (not your regular password)
4. Set `SMTP_USERNAME` to your full Gmail address

### 3. Database Migration

Run the database migration to add email configuration table:

```bash
# Connect to your PostgreSQL database and run:
psql -h your-db-host -U thakii_user -d thakii_production -f scripts/add_email_notifications_table.sql
```

---

## 📨 Email Features

### Automatic Notifications

Emails are automatically sent when:
- ✅ **Video processing completes successfully** (with PDF attached)
- ❌ **Video processing fails** (with error details)

### Email Content

**Success Email Includes:**
- ✅ Success confirmation
- 📎 PDF file attachment
- 📋 Processing details (filename, video ID, timestamp)
- 🔗 Link to dashboard

**Failure Email Includes:**
- ❌ Failure notification
- 🔍 Error details
- 📋 Processing details
- 💡 Troubleshooting suggestions

### Recipients

Each notification is sent to:
1. **Primary User**: The user who uploaded the video
2. **Additional Recipients**: Configured via environment variables or admin API

---

## 🛠️ Admin API Endpoints

### Test Email Configuration

```bash
POST /admin/email/test
Authorization: Bearer <admin-token>
Content-Type: application/json

{
  "recipient": "test@example.com"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Test email sent to test@example.com"
}
```

### Get Email Configuration

```bash
GET /admin/email/config
Authorization: Bearer <admin-token>
```

**Response:**
```json
{
  "configured": true,
  "smtp_server": "smtp.gmail.com",
  "smtp_port": 587,
  "from_email": "your-email@gmail.com",
  "from_name": "Thakii Lecture2PDF",
  "additional_recipients": ["admin@company.com"],
  "has_username": true,
  "has_password": true
}
```

### Update Additional Recipients

```bash
POST /admin/email/recipients
Authorization: Bearer <admin-token>
Content-Type: application/json

{
  "emails": [
    "admin@yourcompany.com",
    "notifications@yourcompany.com",
    "manager@yourcompany.com"
  ]
}
```

**Response:**
```json
{
  "success": true,
  "message": "Updated notification recipients",
  "recipients": [
    "admin@yourcompany.com",
    "notifications@yourcompany.com",
    "manager@yourcompany.com"
  ]
}
```

---

## 🔧 Configuration Options

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SMTP_SERVER` | No | `smtp.gmail.com` | SMTP server hostname |
| `SMTP_PORT` | No | `587` | SMTP server port |
| `SMTP_USERNAME` | **Yes** | - | SMTP authentication username |
| `SMTP_PASSWORD` | **Yes** | - | SMTP authentication password |
| `FROM_EMAIL` | No | Same as username | Sender email address |
| `FROM_NAME` | No | `Thakii Lecture2PDF` | Sender display name |
| `NOTIFICATION_EMAILS` | No | - | Additional recipients (comma-separated) |

### Database Configuration

Additional recipients are stored persistently in the `email_notification_config` table:

```sql
SELECT * FROM email_notification_config WHERE config_key = 'additional_recipients';
```

---

## 🔍 Troubleshooting

### Email Not Sending

1. **Check Configuration**:
   ```bash
   GET /admin/email/config
   ```
   Ensure `configured: true` and credentials are set.

2. **Test Email Service**:
   ```bash
   POST /admin/email/test
   ```
   Send a test email to verify SMTP settings.

3. **Check Logs**:
   Look for email-related messages in backend logs:
   ```bash
   tail -f logs/backend.log | grep -i email
   ```

### Common Issues

**Gmail Authentication Error:**
- Ensure 2FA is enabled
- Use App Password, not regular password
- Check if "Less secure app access" is disabled (it should be)

**SMTP Connection Error:**
- Verify SMTP server and port
- Check firewall/network restrictions
- Ensure TLS/SSL settings are correct

**PDF Attachment Issues:**
- Verify S3 PDF URLs are accessible
- Check file size limits (some email providers limit attachment size)
- Monitor network connectivity for PDF downloads

---

## 📊 Monitoring

### Email Delivery Logs

Monitor email delivery in backend logs:

```bash
# Success
✅ Email notification sent to user@example.com for video abc-123

# Failure
❌ Failed to send email notification: SMTP authentication failed

# PDF Attachment
📎 PDF attached successfully: my-video.pdf
```

### Database Tracking

Email notifications are logged in the notifications table:

```sql
SELECT * FROM notifications 
WHERE type = 'email_notification' 
ORDER BY created_at DESC;
```

---

## 🚀 Advanced Usage

### Custom Email Templates

To customize email templates, modify the `_create_email_body` method in `core/email_service.py`.

### Multiple SMTP Providers

The service supports any SMTP provider. Common configurations:

**Outlook/Hotmail:**
```bash
SMTP_SERVER=smtp-mail.outlook.com
SMTP_PORT=587
```

**Yahoo:**
```bash
SMTP_SERVER=smtp.mail.yahoo.com
SMTP_PORT=587
```

**Custom SMTP:**
Configure according to your provider's documentation.

### Webhook Integration

For advanced integrations, you can extend the `internal_task_update` endpoint to trigger additional webhooks or notifications.

---

## 🔐 Security Considerations

1. **Use App Passwords**: Never use regular email passwords
2. **Environment Variables**: Store credentials securely
3. **SMTP over TLS**: Always use encrypted connections (port 587)
4. **Access Control**: Email admin endpoints require admin authentication
5. **Rate Limiting**: Consider implementing rate limiting for email endpoints

---

## 📝 API Reference Summary

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/admin/email/test` | POST | Admin | Send test email |
| `/admin/email/config` | GET | Admin | Get email configuration |
| `/admin/email/recipients` | POST | Admin | Update additional recipients |
| `/internal/task-update` | POST | Internal | Trigger notifications (used by worker) |

---

## 🎯 Next Steps

1. Configure SMTP settings in your `.env` file
2. Run the database migration
3. Test email functionality using the admin endpoints
4. Configure additional recipients as needed
5. Monitor email delivery in production

For support, check the backend logs and use the test endpoints to diagnose issues.



