# Thakii Backend API - Inputs and Outputs

This document describes the data flow, dependencies, and interfaces for the Thakii Backend API service.

## 📥 INPUTS

### 1. HTTP API Requests
**Source**: thakii-frontend (via thakii-lambda-router)
**Format**: HTTP requests with JSON/FormData payloads
**Endpoints Receiving**:

#### Authentication Required Requests
```http
POST /upload
Headers: 
  Authorization: Bearer <jwt_token>
  Content-Type: multipart/form-data
Body: FormData with video file (up to 2GB)

GET /list
Headers: Authorization: Bearer <jwt_token>

GET /download/{video_id}
Headers: Authorization: Bearer <jwt_token>
Path Parameters: video_id (UUID string)

GET /admin/stats
Headers: Authorization: Bearer <jwt_token>
Required Role: admin or super_admin

POST /admin/users
Headers: 
  Authorization: Bearer <jwt_token>
  Content-Type: application/json
Body: {"email": "admin@example.com", "role": "admin"}
Required Role: super_admin
```

#### Public Endpoints
```http
GET /health
No authentication required
```

### 2. Firebase Authentication Tokens
**Source**: Firebase Auth service (via frontend)
**Format**: JWT tokens in Authorization headers
**Token Structure**:
```json
{
  "iss": "https://securetoken.google.com/project-id",
  "aud": "project-id",
  "auth_time": 1234567890,
  "user_id": "firebase-uid",
  "sub": "firebase-uid",
  "iat": 1234567890,
  "exp": 1234571490,
  "email": "user@example.com",
  "email_verified": true,
  "firebase": {
    "identities": {"email": ["user@example.com"]},
    "sign_in_provider": "password"
  },
  "custom_claims": {
    "role": "user|admin|super_admin"
  }
}
```

### 3. Environment Configuration
**Source**: Environment variables and configuration files
**Format**: Key-value pairs
**Required Variables**:
```env
# Flask Configuration
FLASK_ENV=development|production
PORT=5001

# AWS Configuration
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=secret...
AWS_DEFAULT_REGION=us-east-2
S3_BUCKET_NAME=thakii-video-storage

# Firebase Configuration
FIREBASE_SERVICE_ACCOUNT_KEY=/path/to/service-account.json
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

# Optional Configuration
ALLOWED_ORIGINS=http://localhost:3000,https://app.domain.com
DISABLE_FIREBASE=false
```

### 4. Firebase Service Account
**Source**: Firebase console (downloaded JSON file)
**Format**: Service account credentials JSON
**Structure**:
```json
{
  "type": "service_account",
  "project_id": "your-project-id",
  "private_key_id": "key-id",
  "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n",
  "client_email": "firebase-adminsdk-...@project.iam.gserviceaccount.com",
  "client_id": "client-id",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs"
}
```

### 5. File Uploads
**Source**: Frontend via multipart/form-data
**Format**: Binary video files
**Supported Types**: MP4, AVI, MOV, WMV, MKV
**Size Limit**: 2GB maximum
**Validation**: File type and size checked on receipt

## 📤 OUTPUTS

### 1. HTTP API Responses
**Destination**: thakii-frontend (via thakii-lambda-router)
**Format**: JSON responses with appropriate HTTP status codes

#### Success Responses
```json
// Health Check Response
{
  "service": "Thakii Lecture2PDF Service",
  "status": "healthy",
  "database": "Firestore",
  "storage": "S3",
  "timestamp": "2024-01-01T10:00:00.000000"
}

// Upload Success Response
{
  "video_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "Video uploaded to S3 and queued for processing",
  "s3_key": "videos/550e8400-e29b-41d4-a716-446655440000/lecture.mp4"
}

// Video List Response
[
  {
    "video_id": "550e8400-e29b-41d4-a716-446655440000",
    "filename": "lecture.mp4",
    "status": "done",
    "upload_date": "2024-01-01 10:00:00",
    "user_email": "user@example.com"
  }
]

// Download Response
{
  "download_url": "https://s3.amazonaws.com/bucket/pdfs/video-id.pdf?X-Amz-Expires=3600...",
  "filename": "lecture.pdf"
}

// Admin Stats Response
{
  "total_videos": 1250,
  "in_queue": 15,
  "in_progress": 8,
  "completed": 1200,
  "failed": 27,
  "total_users": 450,
  "active_servers": 3
}
```

#### Error Responses
```json
// Authentication Error
{
  "error": "Authentication required",
  "code": 401,
  "timestamp": "2024-01-01T10:00:00.000000"
}

// Validation Error
{
  "error": "File size must be less than 2GB",
  "code": 400,
  "timestamp": "2024-01-01T10:00:00.000000"
}

// Server Error
{
  "error": "Failed to upload video: S3 connection timeout",
  "code": 500,
  "timestamp": "2024-01-01T10:00:00.000000"
}
```

### 2. AWS S3 Operations
**Destination**: Amazon S3 bucket
**Format**: Binary files and metadata

#### File Uploads
```
Bucket: thakii-video-storage
Key Structure:
- videos/{video_id}/{original_filename}
- subtitles/{video_id}.srt
- pdfs/{video_id}.pdf

Metadata:
- Content-Type: video/mp4, application/pdf, text/plain
- User-ID: Firebase UID
- Upload-Date: ISO timestamp
```

#### Presigned URLs Generated
```
URL Format: https://s3.amazonaws.com/bucket/key?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=...
Expiration: 3600 seconds (1 hour)
Permissions: GET only for specific object
```

### 3. Firestore Database Operations
**Destination**: Firebase Firestore
**Format**: JSON documents

#### Document Creation/Updates
```javascript
// Video Task Creation
firestore.collection('video_tasks').doc(video_id).set({
  video_id: "550e8400-e29b-41d4-a716-446655440000",
  filename: "lecture.mp4",
  user_id: "firebase-uid",
  user_email: "user@example.com",
  status: "in_queue",
  upload_date: "2024-01-01 10:00:00",
  created_at: firestore.SERVER_TIMESTAMP,
  updated_at: firestore.SERVER_TIMESTAMP
});

// Admin User Creation
firestore.collection('admin_users').doc(user_id).set({
  email: "admin@example.com",
  role: "admin",
  status: "active",
  created_by: "super_admin_uid",
  created_at: firestore.SERVER_TIMESTAMP
});

// Server Health Update
firestore.collection('processing_servers').doc(server_id).update({
  status: "healthy",
  last_health_check: firestore.SERVER_TIMESTAMP,
  load_metrics: {
    cpu_usage: 45.2,
    memory_usage: 62.1,
    active_tasks: 3
  }
});
```

### 4. System Logs
**Destination**: Application logs (stdout/stderr, log files)
**Format**: Structured log messages

#### Log Levels and Examples
```python
# Info Logs
print(f"Video uploaded to S3: {video_key}")
print(f"Task created in Firestore: {video_id} for user: {user_email}")

# Error Logs
print(f"Error uploading video: {str(e)}")
print(f"Firebase initialization failed: {e}")

# Debug Logs (development only)
print(f"Processing upload request for user: {current_user['email']}")
print(f"Generated presigned URL with expiration: {expiration}")
```

### 5. Error Notifications
**Destination**: Monitoring systems and error tracking
**Format**: Structured error reports

#### Error Categories
```python
# Client Errors (4xx)
- Authentication failures
- Authorization errors
- Validation errors
- Resource not found

# Server Errors (5xx)
- Database connection failures
- S3 operation failures
- Internal processing errors
- Timeout errors
```

## 🔄 DATA FLOW PATTERNS

### Video Upload Flow
```
Frontend file selection → Multipart upload request → JWT validation → 
File validation → S3 upload → Firestore task creation → Success response
```

### Authentication Flow
```
JWT token from request → Firebase token verification → User extraction → 
Role validation → Request processing or rejection
```

### Download Flow
```
Download request → User ownership validation → S3 presigned URL generation → 
URL response → Frontend triggers download
```

### Admin Operations Flow
```
Admin request → JWT validation → Role verification (admin/super_admin) → 
Firestore operation → Response with updated data
```

## 🔗 DEPENDENCIES

### External Services
- **Firebase Auth**: JWT token verification
- **Firebase Firestore**: Database operations and real-time updates
- **AWS S3**: File storage and retrieval
- **thakii-worker-service**: Consumes tasks created by API

### Internal Dependencies
- **Flask**: Web framework for HTTP handling
- **boto3**: AWS SDK for S3 operations
- **firebase-admin**: Firebase server SDK
- **python-dotenv**: Environment variable management

### System Dependencies
- **Python 3.10+**: Runtime environment
- **Network connectivity**: AWS and Firebase APIs
- **File system**: Temporary file operations

## 🎯 ROLE IN SYSTEM

The Backend API serves as the **central coordination hub** for the Thakii system:

1. **Authentication Gateway**: Validates all user requests
2. **File Upload Orchestrator**: Manages video uploads to S3
3. **Task Coordinator**: Creates and manages processing tasks
4. **Admin Interface**: Provides system management capabilities
5. **Security Layer**: Enforces authorization and validation
6. **Data Bridge**: Connects frontend with storage and processing services

## 🔒 SECURITY CONSIDERATIONS

### Input Validation
- File type and size validation
- JWT token verification on all protected endpoints
- Request payload sanitization
- SQL injection prevention (NoSQL with Firestore)

### Authentication & Authorization
- Firebase JWT token verification
- Role-based access control (RBAC)
- User ownership validation for resources
- Admin privilege escalation protection

### Data Protection
- Secure file upload to S3
- Presigned URLs with expiration
- Encrypted communication (HTTPS)
- Environment variable protection for secrets

## 📊 PERFORMANCE CHARACTERISTICS

### Request Patterns
- **Peak Load**: Video upload operations (large file transfers)
- **Steady State**: Status checks and list operations
- **Admin Load**: Periodic management operations

### Resource Usage
- **CPU**: Low to moderate (mainly I/O bound)
- **Memory**: Moderate (file buffering during uploads)
- **Network**: High during file uploads
- **Storage**: Minimal (temporary file operations only)

### Scalability Considerations
- Stateless design for horizontal scaling
- Database connection pooling
- Efficient S3 operations
- Request timeout management
