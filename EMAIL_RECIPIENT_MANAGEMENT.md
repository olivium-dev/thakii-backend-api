# 📧 Email Recipient Management Guide

## Overview

The Thakii Backend API now supports managing multiple email recipients for notification emails. Admins can add, remove, and list email addresses that will receive notifications whenever a video processing completes.

---

## 🎯 Features

✅ **Add Recipients**: Add individual email addresses to the notification list  
✅ **Remove Recipients**: Remove specific email addresses from the list  
✅ **List Recipients**: View all current notification recipients  
✅ **Update All**: Replace the entire list of recipients at once  
✅ **Email Validation**: Automatic validation of email format  
✅ **Duplicate Prevention**: Cannot add the same email twice  
✅ **Database Persistence**: Recipients are stored permanently in PostgreSQL  
✅ **Admin Only**: All endpoints require admin authentication

---

## 📡 API Endpoints

### 1. Get All Recipients

**Endpoint:** `GET /admin/email/recipients`  
**Auth:** Admin required  
**Description:** Get the current list of notification recipients

**Response:**
```json
{
  "success": true,
  "recipients": [
    "admin@company.com",
    "notifications@company.com"
  ],
  "count": 2
}
```

---

### 2. Add a Recipient

**Endpoint:** `POST /admin/email/recipients/add`  
**Auth:** Admin required  
**Description:** Add a single email to the notification list

**Request Body:**
```json
{
  "email": "newuser@company.com"
}
```

**Success Response (200):**
```json
{
  "success": true,
  "message": "Added newuser@company.com to notification recipients",
  "recipients": [
    "admin@company.com",
    "notifications@company.com",
    "newuser@company.com"
  ]
}
```

**Error Responses:**

**400 - Invalid Email:**
```json
{
  "error": "Invalid email address: not-an-email"
}
```

**400 - Duplicate Email:**
```json
{
  "error": "Email newuser@company.com is already in the recipients list"
}
```

---

### 3. Remove a Recipient

**Endpoint:** `POST /admin/email/recipients/remove`  
**Auth:** Admin required  
**Description:** Remove a single email from the notification list

**Request Body:**
```json
{
  "email": "olduser@company.com"
}
```

**Success Response (200):**
```json
{
  "success": true,
  "message": "Removed olduser@company.com from notification recipients",
  "recipients": [
    "admin@company.com",
    "notifications@company.com"
  ]
}
```

**Error Responses:**

**404 - Email Not Found:**
```json
{
  "error": "Email olduser@company.com is not in the recipients list"
}
```

---

### 4. Update All Recipients (Bulk Replace)

**Endpoint:** `POST /admin/email/recipients`  
**Auth:** Admin required  
**Description:** Replace the entire list of recipients

**Request Body:**
```json
{
  "emails": [
    "new@company.com",
    "team@company.com",
    "manager@company.com"
  ]
}
```

**Success Response (200):**
```json
{
  "success": true,
  "message": "Updated notification recipients",
  "recipients": [
    "new@company.com",
    "team@company.com",
    "manager@company.com"
  ]
}
```

---

## 🔧 Usage Examples

### Using cURL

**Get Recipients:**
```bash
curl -X GET https://thakii-02.fanusdigital.site/thakii-be/admin/email/recipients \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Add a Recipient:**
```bash
curl -X POST https://thakii-02.fanusdigital.site/thakii-be/admin/email/recipients/add \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"email": "newuser@company.com"}'
```

**Remove a Recipient:**
```bash
curl -X POST https://thakii-02.fanusdigital.site/thakii-be/admin/email/recipients/remove \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"email": "olduser@company.com"}'
```

### Using Python

```python
import requests

BACKEND_URL = "https://thakii-02.fanusdigital.site/thakii-be"
ADMIN_TOKEN = "your-admin-token-here"

headers = {
    "Authorization": f"Bearer {ADMIN_TOKEN}",
    "Content-Type": "application/json"
}

# Get recipients
response = requests.get(
    f"{BACKEND_URL}/admin/email/recipients",
    headers=headers
)
print(response.json())

# Add a recipient
response = requests.post(
    f"{BACKEND_URL}/admin/email/recipients/add",
    headers=headers,
    json={"email": "newuser@company.com"}
)
print(response.json())

# Remove a recipient
response = requests.post(
    f"{BACKEND_URL}/admin/email/recipients/remove",
    headers=headers,
    json={"email": "olduser@company.com"}
)
print(response.json())
```

---

## 🛡️ Security & Validation

### Email Validation
All email addresses are validated using regex pattern:
```regex
^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$
```

**Valid Examples:**
- ✅ `user@company.com`
- ✅ `first.last@sub.domain.com`
- ✅ `user+tag@example.co.uk`

**Invalid Examples:**
- ❌ `not-an-email`
- ❌ `@company.com`
- ❌ `user@`
- ❌ `user @company.com` (space)

### Authentication
- All endpoints require admin authentication
- Must include valid admin JWT token in Authorization header
- Returns 401 Unauthorized if not authenticated
- Returns 403 Forbidden if authenticated but not admin

### Database Persistence
- Recipients stored in `email_notification_config` table
- Stored as JSON array in `additional_recipients` key
- Survives server restarts
- Automatically synced between database and in-memory cache

---

## 📊 How It Works

### Email Notification Flow

1. **Video Processing Completes** (success or failure)
2. **Worker calls** `/internal/task-update` with status
3. **Backend retrieves**:
   - User email from database (`video_tasks.user_email`)
   - Additional recipients from database (`email_notification_config`)
4. **Backend sends email via Brevo API** to:
   - Primary user (who uploaded the video)
   - All additional recipients
5. **Email includes**:
   - Success: PDF attachment + processing details
   - Failure: Error message + troubleshooting info

### Recipient Management Flow

```
Admin → POST /admin/email/recipients/add
         ↓
      Validate email format
         ↓
      Check for duplicates
         ↓
      Update database (PostgreSQL)
         ↓
      Update in-memory cache
         ↓
      Return success + updated list
```

---

## 💾 Database Schema

Recipients are stored in the `email_notification_config` table:

```sql
CREATE TABLE email_notification_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    config_key VARCHAR(255) UNIQUE NOT NULL,
    config_value TEXT,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Example Row:**
```
config_key: additional_recipients
config_value: ["admin@company.com", "notifications@company.com"]
description: JSON array of additional email recipients for notifications
```

---

## 🔍 Troubleshooting

### Common Issues

**401 Unauthorized**
- Missing or invalid Authorization header
- Solution: Include valid admin JWT token

**400 Invalid Email**
- Email format is incorrect
- Solution: Check email format matches validation pattern

**400 Duplicate Email**
- Email already exists in recipients list
- Solution: Use GET endpoint to check current list first

**404 Email Not Found**
- Trying to remove an email that doesn't exist
- Solution: Use GET endpoint to verify email exists

### Check Current Configuration

```bash
# Get current recipients
curl -X GET https://thakii-02.fanusdigital.site/thakii-be/admin/email/recipients \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

### Check Database Directly

```bash
ssh ec2-user@192.168.2.71
psql -U thakii_user -d thakii_production

SELECT * FROM email_notification_config 
WHERE config_key = 'additional_recipients';
```

---

## 📝 Best Practices

1. **Use Add/Remove for Individual Changes**: Better than replacing entire list
2. **Validate Recipients**: Test with a single recipient before adding multiple
3. **Keep List Small**: Too many recipients can slow down email sending
4. **Use Team Aliases**: Consider using team@company.com instead of individual emails
5. **Monitor Logs**: Check backend logs to ensure emails are being sent
6. **Test Before Production**: Use test email address first

---

## 🎯 Summary

| Feature | Status |
|---------|--------|
| Add Recipients | ✅ Implemented |
| Remove Recipients | ✅ Implemented |
| List Recipients | ✅ Implemented |
| Bulk Update | ✅ Implemented |
| Email Validation | ✅ Implemented |
| Duplicate Prevention | ✅ Implemented |
| Database Persistence | ✅ Implemented |
| Admin Authentication | ✅ Implemented |
| Error Handling | ✅ Implemented |

**All features are fully implemented and production-ready!** 🎉



