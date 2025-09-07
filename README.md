# Thakii Backend API

Flask-based REST API server for the Thakii Lecture2PDF Service. Handles user authentication, video file management, task coordination, and administrative functions with Firebase and AWS S3 integration.

## 🚀 Features

- **RESTful API**: Clean, documented endpoints following REST principles
- **Firebase Authentication**: JWT token verification and user management
- **AWS S3 Integration**: Direct video upload and presigned URL generation
- **Firestore Database**: Real-time task management and status tracking
- **Admin System**: Role-based access control with admin management
- **CORS Support**: Configurable cross-origin resource sharing
- **Health Monitoring**: Comprehensive health check endpoints
- **Error Handling**: Structured error responses and logging

## 🛠️ Technology Stack

- **Flask**: Python web framework for API development
- **Firebase Admin SDK**: Server-side Firebase integration
- **AWS SDK (boto3)**: S3 and other AWS services
- **Flask-CORS**: Cross-origin resource sharing
- **python-dotenv**: Environment variable management
- **Gunicorn**: WSGI HTTP server for production

## 📁 Project Structure

```
backend-api/
├── api/
│   └── app.py                # Main Flask application
├── core/
│   ├── auth_middleware.py    # Firebase authentication
│   ├── s3_storage.py         # AWS S3 operations
│   ├── firestore_db.py       # Firestore database operations
│   ├── admin_manager.py      # Admin user management
│   ├── server_manager.py     # Processing server management
│   └── push_notification_service.py  # Notification handling
├── requirements.txt          # Python dependencies
├── Dockerfile               # Container configuration
├── docker-compose.yml       # Local development setup
├── .env.example             # Environment variables template
└── deployment/
    ├── ecs-task-definition.json
    └── github-actions/
```

## 🔧 Environment Variables

Create a `.env` file in the root directory:

```env
# Flask Configuration
FLASK_ENV=development
FLASK_DEBUG=True
PORT=5001

# AWS Configuration
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_DEFAULT_REGION=us-east-2
S3_BUCKET_NAME=thakii-video-storage

# Firebase Configuration
FIREBASE_SERVICE_ACCOUNT_KEY=/path/to/firebase-service-account.json
GOOGLE_APPLICATION_CREDENTIALS=/path/to/firebase-service-account.json

# CORS Configuration
ALLOWED_ORIGINS=http://localhost:3000,https://your-frontend-domain.com

# Optional: Disable Firebase for development
DISABLE_FIREBASE=false
```

## 🚀 Getting Started

### Prerequisites
- Python 3.10+
- AWS account with S3 access
- Firebase project with Admin SDK
- Virtual environment (recommended)

### Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/oudaykhaled/thakii-backend-api.git
   cd thakii-backend-api
   ```

2. **Create virtual environment**:
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

5. **Run the application**:
   ```bash
   python api/app.py
   ```

6. **Access the API**:
   API will be available at http://localhost:5001

### Docker Setup

```bash
# Build and run with Docker Compose
docker-compose up --build

# Or with Docker directly
docker build -t thakii-backend-api .
docker run -p 5001:5001 --env-file .env thakii-backend-api
```

## 📡 API Endpoints

### Health Check
```http
GET /health
```
**Response**: Service health status and dependencies

### Authentication Required Endpoints

#### Video Management
```http
POST /upload
Content-Type: multipart/form-data
Authorization: Bearer <jwt_token>
Body: file=<video_file>
```

```http
GET /list
Authorization: Bearer <jwt_token>
```

```http
GET /download/{video_id}
Authorization: Bearer <jwt_token>
```

#### Admin Endpoints (Admin Role Required)
```http
GET /admin/stats
Authorization: Bearer <jwt_token>
```

```http
GET /admin/users
Authorization: Bearer <jwt_token>
```

```http
POST /admin/users
Authorization: Bearer <jwt_token>
Content-Type: application/json
```

```http
GET /admin/servers
Authorization: Bearer <jwt_token>
```

## 🔐 Authentication System

### Firebase JWT Verification
- Validates Firebase ID tokens on protected endpoints
- Extracts user information (uid, email, custom claims)
- Supports role-based access control (user, admin, super_admin)

### Middleware Functions
```python
@require_auth          # Requires valid JWT token
@require_admin         # Requires admin or super_admin role
@require_super_admin   # Requires super_admin role only
```

## 🗄️ Database Integration

### Firestore Collections
```python
# Video tasks
video_tasks/{video_id}
{
    "video_id": "uuid",
    "filename": "video.mp4",
    "user_id": "firebase_uid",
    "user_email": "user@example.com",
    "status": "in_queue|in_progress|done|failed",
    "upload_date": "2024-01-01 10:00:00",
    "created_at": "timestamp",
    "updated_at": "timestamp"
}

# Admin users
admin_users/{user_id}
{
    "email": "admin@example.com",
    "role": "admin|super_admin",
    "status": "active|inactive",
    "created_by": "creator_uid",
    "created_at": "timestamp"
}

# Processing servers
processing_servers/{server_id}
{
    "name": "server-1",
    "url": "https://api.server1.com",
    "status": "healthy|unhealthy",
    "last_health_check": "timestamp",
    "load_metrics": {}
}
```

## ☁️ AWS S3 Integration

### File Operations
- **Video Upload**: Direct upload to S3 with organized folder structure
- **Presigned URLs**: Generate secure download links with expiration
- **File Organization**: 
  - `videos/{video_id}/{filename}` - Original uploads
  - `subtitles/{video_id}.srt` - Generated subtitles  
  - `pdfs/{video_id}.pdf` - Generated PDFs

### S3 Storage Class
```python
class S3Storage:
    def upload_video(self, file_obj, video_id, filename)
    def download_video_to_temp(self, video_id, filename)
    def upload_subtitle(self, subtitle_content, video_id)
    def upload_pdf(self, pdf_path, video_id)
    def generate_presigned_url(self, key, expiration=3600)
    def cleanup_temp_files(self, *file_paths)
```

## 🔒 Security Features

### Input Validation
- File type and size validation
- Request payload validation
- SQL injection prevention (NoSQL with Firestore)

### Authentication & Authorization
- JWT token verification on all protected endpoints
- Role-based access control
- User ownership validation for resources

### CORS Configuration
- Configurable allowed origins
- Credential support for authenticated requests
- Preflight request handling

## 📊 Monitoring & Health Checks

### Health Endpoint Response
```json
{
    "service": "Thakii Lecture2PDF Service",
    "status": "healthy",
    "database": "Firestore",
    "storage": "S3",
    "timestamp": "2024-01-01T10:00:00.000000"
}
```

### Error Handling
- Structured error responses
- Comprehensive logging
- Error categorization (client vs server errors)

## 🚀 Deployment

### Production with Gunicorn
```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5001 api.app:app
```

### AWS ECS Deployment
1. Build Docker image
2. Push to ECR repository
3. Update ECS task definition
4. Deploy to ECS service

### Environment-specific Configuration
- Development: Flask dev server
- Staging: Gunicorn with debug logging
- Production: Gunicorn with optimized settings

## 🧪 Testing

```bash
# Install test dependencies
pip install pytest pytest-cov

# Run unit tests
pytest tests/

# Run with coverage
pytest --cov=api --cov-report=html tests/

# Integration tests
pytest tests/integration/
```

## 📈 Performance Optimization

### Database Optimization
- Firestore indexing for common queries
- Connection pooling
- Query result caching where appropriate

### File Handling
- Streaming file uploads
- Temporary file cleanup
- Efficient S3 operations

### API Performance
- Response compression
- Request timeout configuration
- Connection keep-alive

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/new-feature`
3. Commit changes: `git commit -am 'Add new feature'`
4. Push to branch: `git push origin feature/new-feature`
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🆘 Support

For support and questions:
- Create an issue on GitHub
- Check the API documentation
- Contact the development team

## 🔗 Related Repositories

- [thakii-frontend](https://github.com/oudaykhaled/thakii-frontend) - React web interface
- [thakii-worker-service](https://github.com/oudaykhaled/thakii-worker-service) - Background processing
- [thakii-lambda-router](https://github.com/oudaykhaled/thakii-lambda-router) - Load balancer
- [thakii-infrastructure](https://github.com/oudaykhaled/thakii-infrastructure) - Infrastructure as Code
# GitHub Actions Pipeline with AWS Secrets ✅
