# Thakii Backend API - Flask REST Service

## 🎯 Overview

This repository contains the **Flask REST API** for the Thakii Lecture2PDF Service. It handles authentication, file management, task coordination, and **triggers external worker services** for video processing.

## 🏗️ Architecture Role

This is the **Backend API** component of the Thakii ecosystem:

```
┌─────────────────────────────────────────────────────────────┐
│ THAKII ECOSYSTEM ARCHITECTURE                               │
├─────────────────────────────────────────────────────────────┤
│ Frontend (thakii-frontend)                                  │
│     ↓ HTTP API calls                                        │
│ Backend API (THIS REPO) ← YOU ARE HERE                     │
│     ↓ Triggers worker via HTTP/Queue                       │
│ Worker Service (thakii-worker-service)                     │
│     ↓ Uses                                                  │
│ PDF Engine (thakii-pdf-engine)                            │
└─────────────────────────────────────────────────────────────┘
```

## 🔗 Related Repositories

| Repository | Role | URL |
|------------|------|-----|
| **thakii-backend-api** | **Backend API** (This repo) | https://github.com/olivium-dev/thakii-backend-api.git |
| **thakii-worker-service** | **Background Processing** | https://github.com/olivium-dev/thakii-worker-service.git |
| **thakii-frontend** | **React Web Interface** | https://github.com/olivium-dev/thakii-frontend.git |
| **thakii-pdf-engine** | **PDF Generation Engine** | https://github.com/olivium-dev/thakii-pdf-engine.git |
| **thakii-lambda-router** | **Load Balancer** | https://github.com/olivium-dev/thakii-lambda-router.git |
| **thakii-infrastructure** | **Infrastructure as Code** | https://github.com/olivium-dev/thakii-infrastructure.git |

## 🚀 Core Responsibilities

### ✅ **API Endpoints**
- **Authentication**: Firebase JWT verification and user management
- **Video Upload**: Direct S3 upload with task creation
- **Task Management**: Video processing status and coordination
- **Admin Operations**: User management, system stats, server health

### ✅ **Worker Integration**
- **Task Creation**: Creates Firestore tasks for video processing
- **Worker Triggering**: Communicates with external worker service
- **Status Updates**: Receives and manages processing status updates
- **Result Coordination**: Handles completed video processing results

### ✅ **Data Management**
- **Firestore Integration**: Real-time database operations
- **S3 Storage**: Video upload, PDF storage, presigned URLs
- **User Management**: Authentication, authorization, admin roles

## 🔧 Key Components

### **Core Modules**
- `app.py` - Main Flask application and API endpoints
- `core/auth_middleware.py` - Firebase authentication and authorization
- `core/firestore_db.py` - Database operations and task management
- `core/s3_storage.py` - AWS S3 file operations
- `core/admin_manager.py` - Admin user management
- `core/server_manager.py` - Processing server coordination

### **Worker Integration**
- `trigger_worker_clean.py` - **Local worker trigger script** (for development/testing)
- **Production**: Communicates with separate `thakii-worker-service` repository

## 🎯 Worker Communication

### **Development Mode**
```python
# Local trigger for development/testing
subprocess.Popen([
    sys.executable,
    "trigger_worker_clean.py",
    video_id
])
```

### **Production Mode**
```python
# HTTP call to external worker service
requests.post(f"{WORKER_SERVICE_URL}/process", {
    "video_id": video_id,
    "callback_url": f"{API_URL}/worker/callback"
})
```

## 📊 API Endpoints

### **Authentication**
- `POST /auth/exchange-token` - Exchange Firebase token for custom backend token
- `GET /auth/user` - Get current user information

### **Video Management**
- `POST /upload` - Upload video and create processing task
- `GET /list` - List user's videos (or all for admins)
- `GET /status/{video_id}` - Get video processing status
- `GET /download/{video_id}` - Get PDF download URL

### **Admin Operations**
- `GET /admin/videos` - Get all videos (admin only)
- `DELETE /admin/videos/{video_id}` - Delete video and files (admin only)
- `GET /admin/stats` - System statistics (admin only)
- `GET /admin/servers` - Processing server management (admin only)

### **Health & Monitoring**
- `GET /health` - Service health check
- `POST /admin/test-notification` - Test push notifications (admin only)

## 🔐 Security Features

### **Authentication & Authorization**
- Firebase JWT token verification
- Role-based access control (user, admin, super_admin)
- Custom backend token generation (72-hour expiration)
- Static mock token support for testing

### **Data Protection**
- User data isolation (users see only their videos)
- Admin privilege escalation controls
- Secure file upload validation
- CORS configuration for frontend integration

## 🗄️ Database Schema

### **Firestore Collections**

#### **video_tasks/{video_id}**
```json
{
    "video_id": "uuid",
    "filename": "video.mp4",
    "user_id": "firebase_uid",
    "user_email": "user@example.com",
    "status": "in_queue|processing|completed|failed",
    "created_at": "timestamp",
    "updated_at": "timestamp",
    "pdf_url": "s3://bucket/pdfs/video_id.pdf",
    "subtitle_url": "s3://bucket/subtitles/video_id.srt"
}
```

#### **admin_users/{user_id}**
```json
{
    "email": "admin@example.com",
    "role": "admin|super_admin",
    "status": "active|inactive",
    "created_by": "creator_uid",
    "created_at": "timestamp"
}
```

## ☁️ AWS S3 Integration

### **File Organization**
```
thakii-video-storage-bucket/
├── videos/{video_id}/{filename}     # Original uploads
├── pdfs/{video_id}.pdf              # Generated PDFs
└── subtitles/{video_id}.srt         # Generated subtitles
```

### **Operations**
- Direct video upload from frontend
- Presigned URL generation for downloads
- File cleanup and management
- Cross-service file sharing with worker

## 🚀 Deployment

### **Environment Variables**
```bash
# Flask Configuration
FLASK_ENV=production
PORT=5001

# Firebase Configuration
GOOGLE_CLOUD_PROJECT=thakii-973e3
FIREBASE_PROJECT_ID=thakii-973e3

# AWS Configuration
AWS_DEFAULT_REGION=us-east-2
S3_BUCKET_NAME=thakii-video-storage-1753883631

# CORS Configuration
ALLOWED_ORIGINS=https://thakii-frontend.netlify.app

# Worker Service Integration
WORKER_SERVICE_URL=https://worker.thakii.com
WORKER_API_KEY=your_worker_api_key

# Mock Authentication (for testing)
STATIC_BEARER_TOKEN=thakii-mock-prod-token
```

### **Production Deployment**
```bash
# Install dependencies
pip install -r requirements.txt

# Start with Gunicorn
gunicorn -w 4 -b 0.0.0.0:5001 app:app

# Or use Docker
docker build -t thakii-backend-api .
docker run -p 5001:5001 --env-file .env thakii-backend-api
```

## 🧪 Testing

### **API Testing**
```bash
# Health check
curl https://thakii-02.fanusdigital.site/health

# Upload video (with auth)
curl -X POST \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@video.mp4" \
  https://thakii-02.fanusdigital.site/upload

# Check video status
curl -H "Authorization: Bearer YOUR_TOKEN" \
  https://thakii-02.fanusdigital.site/admin/videos
```

### **Mock Authentication**
```bash
# Use static mock token for testing
export MOCK_TOKEN="thakii-mock-prod-token"
curl -H "Authorization: Bearer $MOCK_TOKEN" \
  https://thakii-02.fanusdigital.site/admin/videos
```

## 🔄 Integration with Worker Service

### **Task Flow**
1. **Frontend** uploads video to **Backend API**
2. **Backend API** stores video in S3 and creates Firestore task
3. **Backend API** triggers **Worker Service** (separate repo)
4. **Worker Service** processes video using **PDF Engine**
5. **Worker Service** updates task status in Firestore
6. **Backend API** serves results to **Frontend**

### **Communication Methods**
- **HTTP API calls** to worker service endpoints
- **Firestore real-time listeners** for status updates
- **S3 shared storage** for file exchange
- **Webhook callbacks** for completion notifications

## 📈 Monitoring & Health

### **Health Checks**
- Database connectivity (Firestore)
- Storage availability (S3)
- Worker service communication
- Authentication service status

### **Logging & Metrics**
- Request/response logging
- Error tracking and categorization
- Performance metrics
- User activity monitoring

## 🤝 Contributing

1. Fork the repository
2. Create feature branch: `git checkout -b feature/new-feature`
3. Make changes to **Backend API** functionality only
4. For worker changes, use: https://github.com/olivium-dev/thakii-worker-service.git
5. Submit pull request with clear description

## 📄 License

This project is licensed under the MIT License.

## 🆘 Support

- **Issues**: Create GitHub issue in this repository
- **Worker Issues**: Use https://github.com/olivium-dev/thakii-worker-service.git
- **Documentation**: Check related repositories for component-specific docs

---

**Repository Role**: Backend API & Task Coordination  
**Worker Processing**: See https://github.com/olivium-dev/thakii-worker-service.git  
**Frontend Interface**: See https://github.com/olivium-dev/thakii-frontend.git
