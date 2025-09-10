import os
import uuid
import datetime
from flask import Flask, request, jsonify, redirect, abort, g
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv
from core.s3_storage import S3Storage
from core.firestore_db import firestore_db
from core.auth_middleware import require_auth, require_admin, get_current_user, is_super_admin, verify_auth_token
from core.custom_auth import custom_token_manager
from core.push_notification_service import push_service
from core.server_manager import server_manager
from core.admin_manager import admin_manager

load_dotenv()

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

@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "service": "Thakii Lecture2PDF Service",
        "status": "healthy",
        "database": "Firestore",
        "storage": "S3",
        "timestamp": datetime.datetime.now().isoformat()
    })

# Optional mock auth endpoints, controlled by env flag ENABLE_MOCK_AUTH=true
if os.getenv('ENABLE_MOCK_AUTH', '').lower() == 'true':
    @app.route("/auth/mock-admin-token", methods=["POST"])
    def generate_mock_admin_token():
        try:
            token = custom_token_manager.generate_mock_token('admin')
            return jsonify({
                "success": True,
                "custom_token": token,
                "expires_in_hours": 72,
                "user": {
                    'uid': 'mock-admin-user-id',
                    'email': 'mock.admin@thakii.test',
                    'name': 'Mock Admin User',
                    'picture': 'https://via.placeholder.com/96x96/4F46E5/FFFFFF?text=MA',
                    'is_admin': True,
                    'mock': True
                },
                "token_type": "custom_backend"
            })
        except Exception as e:
            return jsonify({"error": "Mock token generation failed", "message": str(e)}), 500

    @app.route("/auth/mock-user-token", methods=["POST"])
    def generate_mock_user_token():
        try:
            token = custom_token_manager.generate_mock_token('user')
            return jsonify({
                "success": True,
                "custom_token": token,
                "expires_in_hours": 72,
                "user": {
                    'uid': 'mock-regular-user-id',
                    'email': 'mock.user@thakii.test',
                    'name': 'Mock Regular User',
                    'picture': 'https://via.placeholder.com/96x96/10B981/FFFFFF?text=MU',
                    'is_admin': False,
                    'mock': True
                },
                "token_type": "custom_backend"
            })
        except Exception as e:
            return jsonify({"error": "Mock token generation failed", "message": str(e)}), 500

    @app.route("/auth/mock-static-token", methods=["GET"])
    def get_static_mock_token():
        """Return a single, stable mock token for production testing."""
        try:
            token = custom_token_manager.generate_static_mock_token()
            return jsonify({
                "success": True,
                "custom_token": token,
                "token_type": "custom_backend",
                "note": "Static mock token enabled"
            })
        except Exception as e:
            return jsonify({"error": "Static mock token generation failed", "message": str(e)}), 500

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
    
    # Get current user from auth middleware
    current_user = get_current_user()
    if not current_user:
        return jsonify({"error": "Authentication required"}), 401
    
    video_id = str(uuid.uuid4())
    filename = file.filename

    try:
        # Upload video to S3 instead of local storage
        video_key = s3_storage.upload_video(file, video_id, filename)
        print(f"Video uploaded to S3: {video_key}")
        
        # Create DB record in Firestore with user information
        task_data = firestore_db.create_video_task(
            video_id, 
            filename, 
            current_user['uid'], 
            current_user['email'], 
            "in_queue"
        )
        print(f"Task created in Firestore: {video_id} for user: {current_user['email']}")

        return jsonify({
            "video_id": video_id, 
            "message": "Video uploaded to S3 and queued for processing",
            "s3_key": video_key
        })
    
    except Exception as e:
        print(f"Error uploading video: {str(e)}")
        return jsonify({"error": f"Failed to upload video: {str(e)}"}), 500

@app.route("/list", methods=["GET"])
@require_auth
def list_videos():
    try:
        current_user = get_current_user()
        if not current_user:
            return jsonify({"error": "Authentication required"}), 401
        
        # Regular users see only their videos, admins can see all
        if is_super_admin(current_user['email']):
            tasks = firestore_db.get_all_video_tasks()
        else:
            tasks = firestore_db.get_user_video_tasks(current_user['uid'])
        # Gracefully handle unavailable Firestore (None) or no tasks
        if not tasks:
            return jsonify([])

        # Convert tasks to the expected format
        video_list = []
        for task in tasks:
            # Use the document ID from Firestore as the video ID
            task_id = task.get("id") or task.get("video_id")
            video_list.append({
                "id": task_id,
                "video_name": task.get("filename"),
                "status": task.get("status"),
                "date": task.get("created_at") or task.get("upload_date"),
                "user_email": task.get("user_email")  # Include for admin view
            })
        
        return jsonify(video_list)
    
    except Exception as e:
        print(f"Error fetching video list: {str(e)}")
        return jsonify({"error": f"Failed to fetch videos: {str(e)}"}), 500

@app.route("/status/<video_id>", methods=["GET"])
@require_auth
def get_video_status(video_id):
    try:
        current_user = get_current_user()
        if not current_user:
            return jsonify({"error": "Authentication required"}), 401
            
        task = firestore_db.get_video_task(video_id)
        
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
            
        task = firestore_db.get_video_task(video_id)
        
        if not task:
            return jsonify({"error": "Video not found"}), 404
        
        # Check if user owns this video or is admin
        if not is_super_admin(current_user['email']) and task.get('user_id') != current_user['uid']:
            return jsonify({"error": "Access denied"}), 403
        
        if task.get("status") != "done":
            return jsonify({"error": "PDF not ready yet"}), 400
        
        # Generate presigned URL for PDF download
        download_url = s3_storage.download_pdf(video_id)
        
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
        tasks = firestore_db.get_all_video_tasks()
        # Gracefully handle unavailable Firestore (None) or no tasks
        if not tasks:
            return jsonify([])

        # Convert tasks to the expected format
        video_list = []
        for task in tasks:
            task_id = task.get("id") or task.get("video_id")
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
        firestore_success = firestore_db.delete_video_task(video_id)
        
        # Delete from S3 (video, subtitles, PDF)
        s3_deletions = []
        try:
            # Get video task to find filename
            task = firestore_db.get_video_task(video_id)
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
        stats = firestore_db.get_admin_stats()
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

if __name__ == "__main__":
    # Ensure super admins exist in database on startup
    admin_manager.ensure_super_admins_exist()
    app.run(host="0.0.0.0", port=5001, debug=False)
