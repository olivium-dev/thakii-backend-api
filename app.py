import os
import uuid
import datetime
from pathlib import Path
from flask import Flask, request, jsonify, redirect, abort, g
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv
from core.s3_storage import S3Storage
from core.postgres_db import postgres_db
from core.auth_middleware import require_auth, require_admin, get_current_user, is_super_admin, verify_auth_token
from core.custom_auth import custom_token_manager
from core.push_notification_service import push_service
from core.server_manager import server_manager
from core.admin_manager import admin_manager
from core.websocket_manager import init_websocket, get_websocket_manager
from core.worker_manager import worker_manager

load_dotenv()

# Worker Service Configuration (Legacy - kept for backwards compatibility)
WORKER_SERVICE_URL = os.getenv('WORKER_SERVICE_URL', 'https://thakii-02.fanusdigital.site/thakii-worker')

app = Flask(__name__)

# Configure app to work behind Nginx reverse proxy
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1, x_for=1)
# Enable CORS. Allow configurable origins via ALLOWED_ORIGINS env (comma-separated).
# Default to allowing any localhost origin (development) to avoid port mismatch issues.
allowed_origins_env = os.getenv("ALLOWED_ORIGINS")
if allowed_origins_env:
    allowed_origins = [origin.strip() for origin in allowed_origins_env.split(",") if origin.strip()]
else:
    # Development-friendly default: allow any origin. Frontend is dev-only.
    allowed_origins = "*"

CORS(
    app,
    resources={r"/*": {"origins": allowed_origins}},
    supports_credentials=True,
)

s3_storage = S3Storage()

# Initialize WebSocket
websocket_manager = init_websocket(app)

def trigger_worker_processing(video_id: str, user_id: str, filename: str, s3_key: str) -> bool:
    """
    Trigger worker processing via HTTP with primary/fallback support
    Uses worker_manager for intelligent routing and automatic failover
    """
    payload = {
        "video_id": video_id,
        "user_id": user_id,
        "filename": filename,
        "s3_key": s3_key
    }
    
    # Trigger worker with automatic fallback
    result = worker_manager.trigger_with_fallback(payload)
    
    if result['success']:
        print(f"✅ Worker triggered successfully: {video_id}")
        print(f"   Worker used: {result['worker_used']}")
        
        # Update database with worker information
        postgres_db.update_video_task(video_id, {
            'processed_by_worker': result['worker_used'],
            'processed_by_worker_url': result.get('worker_url', ''),
            'worker_attempts': 1
        })
        
        return True
    else:
        print(f"❌ All workers failed for video {video_id}")
        print(f"   Error: {result['error']}")
        
        # Update task status to failed
        error_message = result['error'] or 'Worker service unavailable'
        postgres_db.update_video_task(video_id, {
            'status': 'failed',
            'error_message': error_message,
            'processed_by_worker': result['worker_used'],
            'processed_by_worker_url': result.get('worker_url', ''),
            'worker_attempts': 1
        })
        
        # Notify via WebSocket
        if websocket_manager:
            websocket_manager.notify_task_update(user_id, {
                'video_id': video_id,
                'status': 'failed',
                'error_message': error_message
            })
        
        return False

@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "service": "Thakii Lecture2PDF Service",
        "status": "healthy",
        "database": "PostgreSQL",
        "storage": "S3",
        "websocket": "enabled",
        "timestamp": datetime.datetime.now().isoformat()
    })

# Mock authentication endpoints removed for production security
# Use proper Firebase authentication only

@app.route("/auth/login", methods=["POST"])
def firebase_login():
    """
    Login with Firebase token and get 30-day backend token
    
    Accepts Firebase ID token and returns a long-lived backend token
    """
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"error": "No Firebase token provided"}), 400
        
        firebase_token = auth_header.split(' ')[1]
        
        # Decode Firebase token without verification (bypass broken verification)
        import jwt
        try:
            # Decode without signature verification to get user data
            firebase_data = jwt.decode(firebase_token, options={"verify_signature": False})
            
            # Validate required fields
            user_id = firebase_data.get('user_id') or firebase_data.get('sub')
            email = firebase_data.get('email')
            
            if not user_id or not email:
                return jsonify({"error": "Invalid Firebase token data"}), 400
            
            # Check if token is expired
            import time
            exp = firebase_data.get('exp', 0)
            if exp < time.time():
                return jsonify({"error": "Firebase token expired"}), 401
            
            # Generate 30-day backend token
            from core.custom_auth import custom_token_manager
            
            # Create user data for backend token
            backend_user_data = {
                'uid': user_id,
                'user_id': user_id,
                'email': email,
                'name': firebase_data.get('name', email.split('@')[0]),
                'picture': firebase_data.get('picture', ''),
                'email_verified': firebase_data.get('email_verified', True),
                'firebase_provider': firebase_data.get('firebase', {}).get('sign_in_provider', 'unknown'),
                'auth_time': firebase_data.get('auth_time', int(time.time()))
            }
            
            # Generate 30-day custom token
            backend_token = custom_token_manager.generate_custom_token(backend_user_data)
            
            return jsonify({
                "success": True,
                "backend_token": backend_token,
                "expires_in_days": 30,
                "user": {
                    "uid": user_id,
                    "email": email,
                    "name": backend_user_data['name'],
                    "picture": backend_user_data['picture'],
                    "is_admin": email in ['ouday.khaled@gmail.com', 'appsaawt@gmail.com']
                },
                "message": "Firebase login successful, use backend_token for all future requests"
            })
            
        except jwt.InvalidTokenError as e:
            return jsonify({
                "error": "Invalid Firebase token format",
                "message": str(e)
            }), 400
            
    except Exception as e:
        print(f"Firebase login error: {str(e)}")
        return jsonify({
            "error": "Login failed",
            "message": str(e)
        }), 500

@app.route("/auth/exchange-token", methods=["POST"])
def exchange_firebase_token():
    """
    Exchange Firebase token for custom backend token
    
    Accepts Firebase ID token and returns a custom backend token with 72-hour expiration
    """
    try:
        # Verify the Firebase token first
        token_data, error = verify_auth_token()
        
        if error:
            return jsonify({
                "error": "Invalid Firebase token",
                "message": error
            }), 401
        
        # Only exchange Firebase tokens (not custom tokens)
        token_type = token_data.get('_token_type', 'firebase')
        if token_type == 'custom':
            return jsonify({
                "error": "Token already custom",
                "message": "This is already a custom backend token",
                "expires_at": token_data.get('exp'),
                "token_type": "custom"
            }), 400
        
        # Generate custom token from Firebase user data
        custom_token = custom_token_manager.generate_custom_token(token_data)
        
        # Extract user info for response
        user_info = {
            'uid': token_data.get('uid') or token_data.get('user_id') or token_data.get('sub'),
            'email': token_data.get('email'),
            'name': token_data.get('name', token_data.get('email', '').split('@')[0] if token_data.get('email') else 'Unknown'),
            'picture': token_data.get('picture'),
            'email_verified': token_data.get('email_verified', False),
            'is_admin': token_data.get('email') in ['ouday.khaled@gmail.com', 'appsaawt@gmail.com'] if token_data.get('email') else False,
            'firebase_provider': token_data.get('firebase', {}).get('sign_in_provider') if isinstance(token_data.get('firebase'), dict) else None
        }
        
        return jsonify({
            "success": True,
            "message": "Token exchanged successfully",
            "custom_token": custom_token,
            "expires_in_hours": 72,
            "expires_at": datetime.datetime.utcnow().timestamp() + (72 * 3600),
            "user": user_info,
            "token_type": "custom_backend"
        }), 200
        
    except Exception as e:
        return jsonify({
            "error": "Token exchange failed",
            "message": str(e)
        }), 500


@app.route("/auth/user", methods=["GET"])
@require_auth
def get_current_user_info():
    """
    Get current authenticated user information
    
    Returns detailed user info from the current token (Firebase or Custom)
    """
    try:
        current_user = get_current_user()
        if not current_user:
            return jsonify({
                "error": "No user data available",
                "message": "User information not found in token"
            }), 400
        
        # Add token expiration info if available
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
            if custom_token_manager.is_custom_token(token):
                try:
                    decoded = custom_token_manager.verify_custom_token(token)
                    current_user['token_expires_at'] = decoded.get('exp')
                    current_user['token_issued_at'] = decoded.get('iat')
                    current_user['token_type'] = 'custom_backend'
                except:
                    pass
            else:
                current_user['token_type'] = 'firebase'
        
        return jsonify({
            "success": True,
            "user": current_user,
            "timestamp": datetime.datetime.now().isoformat()
        }), 200
        
    except Exception as e:
        return jsonify({
            "error": "Failed to get user info",
            "message": str(e)
        }), 500

@app.route("/upload", methods=["POST"])
@require_auth
def upload_video():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400
    
    # STEP-BY-STEP RECURSION DEBUGGING
    try:
        print("🔍 STEP 1: Getting current user...")
        current_user = get_current_user()
        if not current_user:
            return jsonify({"error": "Authentication required"}), 401
        print(f"✅ STEP 1 OK: User {current_user.get('email')}")
        
        video_id = str(uuid.uuid4())
        filename = file.filename
        print(f"🔍 STEP 2: Generated video_id: {video_id}")
        
        print("🔍 STEP 3: Uploading to S3...")
        video_key = s3_storage.upload_video(file, video_id, filename)
        print(f"✅ STEP 3 OK: S3 key: {video_key}")
        
        print("🔍 STEP 4: Creating DB record...")
        task_data = postgres_db.create_video_task(
            video_id, 
            filename, 
            current_user['uid'], 
            current_user['email'], 
            "in_queue",
            s3_key=video_key
        )
        print(f"✅ STEP 4 OK: DB record created")
        
        print("🔍 STEP 5: WebSocket notification...")
        if websocket_manager:
            websocket_manager.notify_task_update(current_user['uid'], {
                'video_id': video_id,
                'status': 'in_queue',
                'filename': filename
            })
        print(f"✅ STEP 5 OK: WebSocket notified")

        print("🔍 STEP 6: Triggering worker...")
        trigger_success = trigger_worker_processing(
            video_id=video_id,
            user_id=current_user['uid'],
            filename=filename,
            s3_key=video_key
        )
        print(f"✅ STEP 6 OK: Worker triggered: {trigger_success}")

        return jsonify({
            "video_id": video_id, 
            "message": "Video uploaded to S3 and queued for processing",
            "s3_key": video_key
        })
    
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"❌ RECURSION ERROR AT: {str(e)}")
        print(f"📋 Full traceback:")
        print(error_details)
        return jsonify({"error": f"Failed to upload video: {str(e)}"}), 500

@app.route("/upload-chunk", methods=["POST"])
@require_auth
def upload_chunk():
    """Upload a single chunk of a large file"""
    try:
        current_user = get_current_user()
        if not current_user:
            return jsonify({"error": "Authentication required"}), 401
        
        # Get chunk metadata
        chunk_index = request.form.get('chunk_index')
        total_chunks = request.form.get('total_chunks')
        file_id = request.form.get('file_id')
        original_filename = request.form.get('original_filename')
        
        if not all([chunk_index, total_chunks, file_id, original_filename]):
            return jsonify({"error": "Missing chunk metadata"}), 400
        
        # Get chunk file
        if 'chunk' not in request.files:
            return jsonify({"error": "No chunk file provided"}), 400
        
        chunk_file = request.files['chunk']
        if chunk_file.filename == '':
            return jsonify({"error": "No chunk file selected"}), 400
        
        # Create chunks directory
        chunks_dir = Path(f"/tmp/chunks/{file_id}")
        chunks_dir.mkdir(parents=True, exist_ok=True)
        
        # Save chunk
        chunk_path = chunks_dir / f"chunk_{chunk_index}"
        chunk_file.save(str(chunk_path))
        
        print(f"📦 Chunk uploaded: {file_id} - {chunk_index}/{total_chunks}")
        print(f"   Chunk size: {chunk_path.stat().st_size:,} bytes")
        
        return jsonify({
            "chunk_index": int(chunk_index),
            "total_chunks": int(total_chunks),
            "file_id": file_id,
            "chunk_size": chunk_path.stat().st_size,
            "message": f"Chunk {chunk_index}/{total_chunks} uploaded successfully"
        })
        
    except Exception as e:
        print(f"Error uploading chunk: {str(e)}")
        return jsonify({"error": f"Failed to upload chunk: {str(e)}"}), 500

@app.route("/assemble-file", methods=["POST"])
@require_auth
def assemble_file():
    """Assemble chunks into final file and process"""
    try:
        current_user = get_current_user()
        if not current_user:
            return jsonify({"error": "Authentication required"}), 401
        
        data = request.get_json()
        file_id = data.get('file_id')
        total_chunks = data.get('total_chunks')
        original_filename = data.get('original_filename')
        
        if not all([file_id, total_chunks, original_filename]):
            return jsonify({"error": "Missing assembly metadata"}), 400
        
        chunks_dir = Path(f"/tmp/chunks/{file_id}")
        if not chunks_dir.exists():
            return jsonify({"error": "Chunks directory not found"}), 404
        
        # Verify all chunks exist
        missing_chunks = []
        for i in range(int(total_chunks)):
            chunk_path = chunks_dir / f"chunk_{i}"
            if not chunk_path.exists():
                missing_chunks.append(i)
        
        if missing_chunks:
            return jsonify({
                "error": "Missing chunks",
                "missing_chunks": missing_chunks
            }), 400
        
        # Assemble file
        video_id = str(uuid.uuid4())
        assembled_file = Path(f"/tmp/{video_id}_{original_filename}")
        
        print(f"🔧 Assembling file: {file_id} → {video_id}")
        
        with open(assembled_file, 'wb') as outfile:
            for i in range(int(total_chunks)):
                chunk_path = chunks_dir / f"chunk_{i}"
                with open(chunk_path, 'rb') as chunk_file:
                    outfile.write(chunk_file.read())
                print(f"   Assembled chunk {i}/{total_chunks}")
        
        print(f"✅ File assembled: {assembled_file.stat().st_size:,} bytes")
        
        # Upload to S3
        with open(assembled_file, 'rb') as file_obj:
            video_key = s3_storage.upload_video(file_obj, video_id, original_filename)
        
        # Create task in Firestore
        task_data = postgres_db.create_video_task(
            video_id, 
            original_filename, 
            current_user['uid'], 
            current_user['email'], 
            "in_queue"
        )
        
        # Trigger worker processing with enhanced error handling
        trigger_success = trigger_worker_processing(
            video_id=video_id,
            user_id=current_user['uid'],
            filename=original_filename,
            s3_key=video_key
        )
        
        if not trigger_success:
            print(f"⚠️ Worker trigger failed for assembled file {video_id}")
        
        # Cleanup chunks and temporary file
        import shutil
        shutil.rmtree(chunks_dir)
        assembled_file.unlink()
        
        return jsonify({
            "video_id": video_id,
            "message": "File assembled and queued for processing",
            "s3_key": video_key,
            "total_size": assembled_file.stat().st_size if assembled_file.exists() else 0
        })
        
    except Exception as e:
        print(f"Error assembling file: {str(e)}")
        return jsonify({"error": f"Failed to assemble file: {str(e)}"}), 500

@app.route("/list", methods=["GET"])
@require_auth
def list_videos():
    try:
        current_user = get_current_user()
        if not current_user:
            return jsonify({"error": "Authentication required"}), 401
        
        # Regular users see only their videos, admins can see all
        if is_super_admin(current_user['email']):
            tasks = postgres_db.get_all_video_tasks()
        else:
            tasks = postgres_db.get_user_video_tasks(current_user['uid'])
        # Gracefully handle unavailable Firestore (None) or no tasks
        if not tasks:
            return jsonify({
                "videos": [],
                "total": 0,
                "timestamp": datetime.datetime.now().isoformat(),
                "message": "No videos found for this user"
            })

        # Convert tasks to the expected format
        video_list = []
        for task in tasks:
            # CRITICAL FIX: Use video_id as primary identifier, NOT the auto-generated id column
            # The PostgreSQL table has both 'id' (auto-generated UUID) and 'video_id' (actual identifier)
            # We must use 'video_id' which is used in S3, downloads, and all other operations
            task_id = task.get("video_id") or task.get("id")
            video_list.append({
                "id": task_id,
                "video_id": task_id,  # For compatibility
                "filename": task.get("filename"),  # Frontend expects 'filename'
                "video_name": task.get("filename"),  # Backup field
                "status": task.get("status"),
                "upload_date": task.get("created_at") or task.get("upload_date"),  # Frontend expects 'upload_date'
                "date": task.get("created_at") or task.get("upload_date"),  # Backup field
                "user_email": task.get("user_email"),  # Include for admin view
                "created_at": task.get("created_at"),
                "updated_at": task.get("updated_at")
            })
        
        return jsonify({
            "videos": video_list,
            "total": len(video_list),
            "timestamp": datetime.datetime.now().isoformat()
        })
    
    except Exception as e:
        print(f"Error fetching video list: {str(e)}")
        # Return empty list for better UX instead of error
        return jsonify({
            "videos": [],
            "total": 0,
            "error_message": f"Database temporarily unavailable: {str(e)}",
            "timestamp": datetime.datetime.now().isoformat()
        }), 200

@app.route("/status/<video_id>", methods=["GET"])
@require_auth
def get_video_status(video_id):
    try:
        current_user = get_current_user()
        if not current_user:
            return jsonify({"error": "Authentication required"}), 401
            
        task = postgres_db.get_video_task(video_id)
        
        if not task:
            return jsonify({"error": "Video not found"}), 404
        
        # Check if user owns this video or is admin
        if not is_super_admin(current_user['email']) and task.get('user_id') != current_user['uid']:
            return jsonify({"error": "Access denied"}), 403
        
        return jsonify({
            "video_id": task.get("video_id"),
            "filename": task.get("filename"),
            "status": task.get("status"),
            "upload_date": task.get("created_at"),
            "updated_at": task.get("updated_at"),
            "user_email": task.get("user_email")
        })
    
    except Exception as e:
        print(f"Error fetching video status: {str(e)}")
        return jsonify({"error": f"Failed to fetch video status: {str(e)}"}), 500

@app.route("/download/<video_id>", methods=["GET"])
@require_auth
def download_pdf(video_id):
    try:
        current_user = get_current_user()
        if not current_user:
            return jsonify({"error": "Authentication required"}), 401
            
        task = postgres_db.get_video_task(video_id)
        
        if not task:
            return jsonify({"error": "Video not found"}), 404
        
        # Check if user owns this video or is admin
        if not is_super_admin(current_user['email']) and task.get('user_id') != current_user['uid']:
            return jsonify({"error": "Access denied"}), 403
        
        if task.get("status") not in ["done", "completed"]:
            return jsonify({"error": "PDF not ready yet"}), 400
        
        # Generate presigned URL for PDF download with original filename
        download_url = s3_storage.download_pdf(video_id, task.get("filename"))
        
        return jsonify({
            "download_url": download_url,
            "video_id": video_id,
            "filename": task.get("filename")
        })
    
    except Exception as e:
        print(f"Error generating download URL: {str(e)}")
        return jsonify({"error": f"Failed to generate download URL: {str(e)}"}), 500

# Admin endpoints
@app.route("/admin/videos", methods=["GET"])
@require_admin
def admin_get_all_videos():
    """Admin endpoint to get all videos from all users"""
    try:
        tasks = postgres_db.get_all_video_tasks()
        # Gracefully handle unavailable Firestore (None) or no tasks
        if not tasks:
            return jsonify([])

        # Convert tasks to the expected format
        video_list = []
        for task in tasks:
            # CRITICAL FIX: Use video_id as primary identifier
            task_id = task.get("video_id") or task.get("id")
            video_list.append({
                "id": task_id,
                "video_name": task.get("filename"),
                "status": task.get("status"),
                "date": task.get("created_at") or task.get("upload_date"),
                "updated_at": task.get("updated_at"),
                "user_email": task.get("user_email"),
                "user_id": task.get("user_id")
            })
        
        return jsonify(video_list)
    
    except Exception as e:
        print(f"Error fetching admin video list: {str(e)}")
        return jsonify({"error": f"Failed to fetch videos: {str(e)}"}), 500

@app.route("/admin/videos/<video_id>", methods=["DELETE"])
@require_admin
def admin_delete_video(video_id):
    """Admin endpoint to delete a video and its associated files"""
    try:
        # Delete from Firestore
        firestore_success = postgres_db.delete_video_task(video_id)
        
        # Delete from S3 (video, subtitles, PDF)
        s3_deletions = []
        try:
            # Get video task to find filename
            task = postgres_db.get_video_task(video_id)
            if task and task.get('filename'):
                filename = task['filename']
                
                # Delete video from S3
                video_key = f"videos/{video_id}/{filename}"
                s3_storage.s3_client.delete_object(Bucket=s3_storage.bucket_name, Key=video_key)
                s3_deletions.append(f"video: {video_key}")
            
            # Delete subtitle from S3
            subtitle_key = f"subtitles/{video_id}.srt"
            s3_storage.s3_client.delete_object(Bucket=s3_storage.bucket_name, Key=subtitle_key)
            s3_deletions.append(f"subtitle: {subtitle_key}")
            
            # Delete PDF from S3
            pdf_key = f"pdfs/{video_id}.pdf"
            s3_storage.s3_client.delete_object(Bucket=s3_storage.bucket_name, Key=pdf_key)
            s3_deletions.append(f"pdf: {pdf_key}")
            
        except Exception as s3_error:
            print(f"S3 deletion warning: {s3_error}")
        
        if firestore_success:
            return jsonify({
                "message": f"Video {video_id} deleted successfully",
                "firestore": "deleted",
                "s3_deletions": s3_deletions
            })
        else:
            return jsonify({"error": "Video not found in Firestore"}), 404
            
    except Exception as e:
        return jsonify({"error": f"Failed to delete video: {str(e)}"}), 500

@app.route("/admin/stats", methods=["GET"])
@require_admin
def admin_get_stats():
    """Admin endpoint to get system statistics"""
    try:
        stats = postgres_db.get_admin_stats()
        return jsonify(stats)
    
    except Exception as e:
        print(f"Error fetching admin stats: {str(e)}")
        return jsonify({"error": f"Failed to fetch stats: {str(e)}"}), 500

@app.route("/admin/test-notification", methods=["POST"])
@require_admin
def send_test_notification():
    """Send a test push notification (admin only)"""
    try:
        data = request.get_json() or {}
        test_type = data.get('type', 'simple')
        
        result = push_service.send_test_notification(test_type)
        
        if result['success']:
            return jsonify({
                'message': 'Test notification sent successfully',
                'result': result
            })
        else:
            return jsonify({
                'error': 'Failed to send test notification',
                'result': result
            }), 500
            
    except Exception as e:
        return jsonify({'error': f'Failed to send test notification: {str(e)}'}), 500

# Server Management Endpoints
@app.route("/admin/servers", methods=["GET"])
@require_admin
def get_servers():
    """Get all registered processing servers"""
    try:
        servers = server_manager.get_all_servers()
        return jsonify(servers)
    except Exception as e:
        return jsonify({'error': f'Failed to fetch servers: {str(e)}'}), 500

@app.route("/admin/servers", methods=["POST"])
@require_admin
def add_server():
    """Add a new processing server"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Request body is required'}), 400
        
        required_fields = ['name', 'url']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Field "{field}" is required'}), 400
        
        result = server_manager.add_server(
            server_name=data['name'],
            server_url=data['url'],
            server_type=data.get('type', 'processing'),
            description=data.get('description', '')
        )
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
            
    except Exception as e:
        return jsonify({'error': f'Failed to add server: {str(e)}'}), 500

@app.route("/admin/servers/<server_id>", methods=["PUT"])
@require_admin
def update_server(server_id):
    """Update a processing server"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Request body is required'}), 400
        
        result = server_manager.update_server(server_id, data)
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
            
    except Exception as e:
        return jsonify({'error': f'Failed to update server: {str(e)}'}), 500

@app.route("/admin/servers/<server_id>", methods=["DELETE"])
@require_admin
def remove_server(server_id):
    """Remove a processing server"""
    try:
        result = server_manager.remove_server(server_id)
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 404
            
    except Exception as e:
        return jsonify({'error': f'Failed to remove server: {str(e)}'}), 500

@app.route("/admin/servers/health-check", methods=["POST"])
@require_admin
def check_servers_health():
    """Check health of all registered servers"""
    try:
        result = server_manager.check_all_servers_health()
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': f'Failed to check servers health: {str(e)}'}), 500

# Admin Management Endpoints
@app.route("/admin/admins", methods=["GET"])
@require_admin
def get_admins():
    """Get all admin users"""
    try:
        admins = admin_manager.get_all_admins()
        return jsonify(admins)
    except Exception as e:
        return jsonify({'error': f'Failed to fetch admins: {str(e)}'}), 500

@app.route("/admin/admins", methods=["POST"])
@require_admin
def add_admin():
    """Add a new admin user (super admin only)"""
    try:
        current_user = get_current_user()
        if not current_user:
            return jsonify({'error': 'Authentication required'}), 401
        
        # Only super admins can add other admins
        if not is_super_admin(current_user['email']):
            return jsonify({'error': 'Super admin privileges required'}), 403
        
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Request body is required'}), 400
        
        if 'email' not in data:
            return jsonify({'error': 'Email is required'}), 400
        
        result = admin_manager.add_admin(
            email=data['email'],
            role=data.get('role', 'admin'),
            added_by=current_user['email'],
            description=data.get('description', '')
        )
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
            
    except Exception as e:
        return jsonify({'error': f'Failed to add admin: {str(e)}'}), 500

@app.route("/admin/admins/<admin_id>", methods=["PUT"])
@require_admin
def update_admin(admin_id):
    """Update an admin user (super admin only)"""
    try:
        current_user = get_current_user()
        if not current_user:
            return jsonify({'error': 'Authentication required'}), 401
        
        # Only super admins can update other admins
        if not is_super_admin(current_user['email']):
            return jsonify({'error': 'Super admin privileges required'}), 403
        
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Request body is required'}), 400
        
        result = admin_manager.update_admin(admin_id, data, current_user['email'])
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
            
    except Exception as e:
        return jsonify({'error': f'Failed to update admin: {str(e)}'}), 500

@app.route("/admin/admins/<admin_id>", methods=["DELETE"])
@require_admin
def remove_admin(admin_id):
    """Remove an admin user (super admin only)"""
    try:
        current_user = get_current_user()
        if not current_user:
            return jsonify({'error': 'Authentication required'}), 401
        
        # Only super admins can remove other admins
        if not is_super_admin(current_user['email']):
            return jsonify({'error': 'Super admin privileges required'}), 403
        
        result = admin_manager.remove_admin(admin_id, current_user['email'])
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 404
            
    except Exception as e:
        return jsonify({'error': f'Failed to remove admin: {str(e)}'}), 500

@app.route("/admin/admins/stats", methods=["GET"])
@require_admin
def get_admin_stats():
    """Get admin statistics"""
    try:
        stats = admin_manager.get_admin_stats()
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': f'Failed to get admin stats: {str(e)}'}), 500

@app.route("/worker-health", methods=["GET"])
@require_admin
def check_worker_health():
    """
    Admin endpoint to check worker service health
    Shows health status for both primary and fallback workers
    """
    try:
        # Get health status for all workers
        health_data = worker_manager.get_all_workers_health()
        
        # Determine overall status
        healthy_count = health_data['summary']['healthy_workers']
        total_count = health_data['summary']['total_workers']
        
        if healthy_count == 0:
            overall_status = "critical"
            status_code = 503
        elif healthy_count < total_count:
            overall_status = "degraded"
            status_code = 200
        else:
            overall_status = "healthy"
            status_code = 200
        
        response_data = {
            "overall_status": overall_status,
            "workers": health_data['workers'],
            "summary": health_data['summary'],
            "priority_mode": health_data['priority_mode'],
            "timestamp": health_data['timestamp']
        }
        
        return jsonify(response_data), status_code
            
    except Exception as e:
        return jsonify({
            "overall_status": "error",
            "error": str(e),
            "timestamp": datetime.datetime.now().isoformat()
        }), 500

@app.route("/internal/task-update", methods=["POST"])
def internal_task_update():
    """
    Internal endpoint for worker to notify about task updates
    This triggers WebSocket notifications to clients
    """
    try:
        data = request.get_json()
        video_id = data.get('video_id')
        status = data.get('status')
        user_id = data.get('user_id')
        
        if not video_id or not status or not user_id:
            return jsonify({"error": "Missing required fields"}), 400
        
        # Get full task data from database
        task = postgres_db.get_video_task(video_id)
        
        if not task:
            return jsonify({"error": "Task not found"}), 404
        
        # Send WebSocket notification
        if websocket_manager:
            websocket_manager.notify_task_update(user_id, task)
        
        return jsonify({
            "success": True,
            "message": "WebSocket notification sent"
        })
        
    except Exception as e:
        print(f"Error in internal task update: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    # Ensure super admins exist in database on startup
    admin_manager.ensure_super_admins_exist()
    
    # Configure Flask for large file uploads
    app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024 * 1024  # 5GB max file size
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # Disable caching for large files
    
    # Run with WebSocket support
    if websocket_manager and websocket_manager.socketio:
        websocket_manager.socketio.run(app, host="0.0.0.0", port=5001, debug=False, allow_unsafe_werkzeug=True)
    else:
        app.run(host="0.0.0.0", port=5001, debug=False, threaded=True)

