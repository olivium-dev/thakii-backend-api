#!/usr/bin/env python3
"""
Unit tests for core modules
Tests auth, database, storage, and other core functionality
"""
import pytest
import os
import sys
from unittest.mock import Mock, patch, MagicMock
import tempfile
import json
import datetime

# Add the parent directory to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class TestAuthMiddleware:
    """Test authentication middleware"""
    
    @patch.dict(os.environ, {'DISABLE_FIREBASE': 'true'})
    def test_super_admin_check(self):
        """Test super admin validation"""
        from core.auth_middleware import is_super_admin
        
        assert is_super_admin('ouday.khaled@gmail.com') == True
        assert is_super_admin('appsaawt@gmail.com') == True
        assert is_super_admin('regular@user.com') == False
        assert is_super_admin('') == False
    
    @patch('firebase_admin._apps', {})
    @patch('core.auth_middleware._verify_with_jwks')
    def test_verify_auth_token_success(self, mock_jwks_verify):
        """Test successful token verification with JWKS fallback"""
        from core.auth_middleware import verify_auth_token
        from flask import Flask
        
        # Mock JWKS verification
        mock_jwks_verify.return_value = {
            'uid': 'test-uid',
            'email': 'test@example.com',
            'email_verified': True
        }
        
        app = Flask(__name__)
        # Use a proper JWT format token
        jwt_token = 'eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiIsImtpZCI6InRlc3Qta2V5In0.eyJ1aWQiOiJ0ZXN0LXVpZCIsImVtYWlsIjoidGVzdEBleGFtcGxlLmNvbSIsImVtYWlsX3ZlcmlmaWVkIjp0cnVlfQ.test-signature'
        with app.test_request_context(headers={'Authorization': f'Bearer {jwt_token}'}):
            result, error = verify_auth_token()
            assert error is None
            assert result['uid'] == 'test-uid'
            assert result['email'] == 'test@example.com'
    
    def test_verify_auth_token_no_header(self):
        """Test token verification without auth header"""
        from core.auth_middleware import verify_auth_token
        from flask import Flask
        
        app = Flask(__name__)
        with app.test_request_context():
            result, error = verify_auth_token()
            assert result is None
            assert 'No Authorization header' in error
    
    def test_verify_auth_token_invalid_format(self):
        """Test token verification with invalid header format"""
        from core.auth_middleware import verify_auth_token
        from flask import Flask
        
        app = Flask(__name__)
        with app.test_request_context(headers={'Authorization': 'InvalidFormat token'}):
            result, error = verify_auth_token()
            assert result is None
            assert 'Invalid Authorization header format' in error

class TestFirestoreDB:
    """Test Firestore database operations"""
    
    @patch.dict(os.environ, {'DISABLE_FIREBASE': 'true'})
    def test_firestore_disabled(self):
        """Test Firestore when disabled"""
        from core.firestore_db import FirestoreDB
        
        db = FirestoreDB()
        assert not db._is_available()
        
        result = db.create_video_task('test-id', 'test.mp4', 'user-id', 'test@example.com')
        assert result is None
    
    @patch('core.firestore_db.firestore.client')
    @patch('core.firestore_db.firebase_admin.initialize_app')
    def test_create_video_task(self, mock_init_app, mock_firestore_client):
        """Test video task creation"""
        from core.firestore_db import FirestoreDB
        
        # Mock Firestore client
        mock_db = MagicMock()
        mock_firestore_client.return_value = mock_db
        
        # Mock document reference
        mock_doc_ref = MagicMock()
        mock_db.collection.return_value.document.return_value = mock_doc_ref
        
        db = FirestoreDB()
        db.db = mock_db  # Override the db instance
        
        result = db.create_video_task('test-id', 'test.mp4', 'user-id', 'test@example.com', 'in_queue')
        
        assert result is not None
        assert result['video_id'] == 'test-id'
        assert result['filename'] == 'test.mp4'
        assert result['user_id'] == 'user-id'
        assert result['user_email'] == 'test@example.com'
        assert result['status'] == 'in_queue'
        
        # Verify Firestore was called
        mock_db.collection.assert_called_with('video_tasks')
        mock_doc_ref.set.assert_called_once()
    
    @patch('core.firestore_db.firestore.client')
    def test_get_video_task_exists(self, mock_firestore_client):
        """Test getting existing video task"""
        from core.firestore_db import FirestoreDB
        
        # Mock Firestore client and document
        mock_db = MagicMock()
        mock_firestore_client.return_value = mock_db
        
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {
            'video_id': 'test-id',
            'filename': 'test.mp4',
            'status': 'done'
        }
        
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc
        
        db = FirestoreDB()
        db.db = mock_db
        
        result = db.get_video_task('test-id')
        assert result is not None
        assert result['video_id'] == 'test-id'
        assert result['filename'] == 'test.mp4'
    
    @patch('core.firestore_db.firestore.client')
    def test_get_video_task_not_exists(self, mock_firestore_client):
        """Test getting non-existent video task"""
        from core.firestore_db import FirestoreDB
        
        # Mock Firestore client and document
        mock_db = MagicMock()
        mock_firestore_client.return_value = mock_db
        
        mock_doc = MagicMock()
        mock_doc.exists = False
        
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc
        
        db = FirestoreDB()
        db.db = mock_db
        
        result = db.get_video_task('non-existent-id')
        assert result is None

class TestS3Storage:
    """Test S3 storage operations"""
    
    @patch('boto3.client')
    def test_s3_storage_init(self, mock_boto_client):
        """Test S3Storage initialization"""
        from core.s3_storage import S3Storage
        
        storage = S3Storage()
        # In test environment, bucket name comes from S3_BUCKET_NAME env var
        assert storage.bucket_name == 'test-bucket'
        assert storage.region == 'us-east-2'
        mock_boto_client.assert_called_with('s3')
    
    @patch('boto3.client')
    def test_upload_video_success(self, mock_boto_client):
        """Test successful video upload"""
        from core.s3_storage import S3Storage
        
        mock_s3_client = MagicMock()
        mock_boto_client.return_value = mock_s3_client
        
        storage = S3Storage()
        
        # Mock file object
        mock_file = MagicMock()
        
        result = storage.upload_video(mock_file, 'test-id', 'test.mp4')
        
        assert result == 'videos/test-id/test.mp4'
        mock_s3_client.upload_fileobj.assert_called_once_with(
            mock_file, storage.bucket_name, 'videos/test-id/test.mp4'
        )
    
    @patch('boto3.client')
    def test_download_pdf_success(self, mock_boto_client):
        """Test PDF download URL generation"""
        from core.s3_storage import S3Storage
        
        mock_s3_client = MagicMock()
        mock_boto_client.return_value = mock_s3_client
        mock_s3_client.generate_presigned_url.return_value = 'https://s3.amazonaws.com/bucket/pdfs/test-id.pdf'
        
        storage = S3Storage()
        
        result = storage.download_pdf('test-id')
        
        assert result == 'https://s3.amazonaws.com/bucket/pdfs/test-id.pdf'
        # Check the actual call made (S3 key format may have changed)
        mock_s3_client.generate_presigned_url.assert_called_once()
        call_args = mock_s3_client.generate_presigned_url.call_args
        assert call_args[0][0] == 'get_object'
        assert 'test-id' in call_args[1]['Params']['Key']  # Key contains test-id
        assert call_args[1]['ExpiresIn'] == 3600
    
    @patch('boto3.client')
    @patch('tempfile.NamedTemporaryFile')
    def test_download_video_to_temp(self, mock_tempfile, mock_boto_client):
        """Test video download to temporary file"""
        from core.s3_storage import S3Storage
        
        mock_s3_client = MagicMock()
        mock_boto_client.return_value = mock_s3_client
        
        mock_temp_file = MagicMock()
        mock_temp_file.name = '/tmp/test_video.mp4'
        mock_tempfile.return_value = mock_temp_file
        
        storage = S3Storage()
        
        result = storage.download_video_to_temp('test-id', 'test.mp4')
        
        assert result == '/tmp/test_video.mp4'
        mock_s3_client.download_fileobj.assert_called_once()
        mock_temp_file.close.assert_called_once()

class TestAdminManager:
    """Test admin management functionality"""
    
    @patch('core.admin_manager.firestore_db')
    def test_add_admin_success(self, mock_firestore_db):
        """Test successful admin addition"""
        from core.admin_manager import AdminManager
        
        # Mock Firestore operations
        mock_firestore_db.db.collection.return_value.add.return_value = (None, MagicMock(id='new-admin-id'))
        
        admin_manager = AdminManager()
        admin_manager.get_all_admins = MagicMock(return_value=[])  # No existing admins
        
        result = admin_manager.add_admin(
            email='new@admin.com',
            role='admin',
            added_by='super@admin.com',
            description='Test admin'
        )
        
        assert result['success'] == True
        assert result['admin']['email'] == 'new@admin.com'
        assert result['admin']['role'] == 'admin'
        assert result['admin']['id'] == 'new-admin-id'
    
    def test_add_admin_invalid_email(self):
        """Test admin addition with invalid email"""
        from core.admin_manager import AdminManager
        
        admin_manager = AdminManager()
        
        result = admin_manager.add_admin(email='invalid-email')
        
        assert result['success'] == False
        assert 'Invalid email format' in result['error']
    
    def test_add_admin_already_exists(self):
        """Test admin addition when admin already exists"""
        from core.admin_manager import AdminManager
        
        admin_manager = AdminManager()
        admin_manager.get_all_admins = MagicMock(return_value=[
            {'email': 'existing@admin.com'}
        ])
        
        result = admin_manager.add_admin(email='existing@admin.com')
        
        assert result['success'] == False
        assert 'already exists' in result['error']
    
    def test_is_super_admin(self):
        """Test super admin check"""
        from core.admin_manager import AdminManager
        
        admin_manager = AdminManager()
        
        assert admin_manager.is_super_admin('ouday.khaled@gmail.com') == True
        assert admin_manager.is_super_admin('appsaawt@gmail.com') == True
        assert admin_manager.is_super_admin('regular@user.com') == False

class TestServerManager:
    """Test server management functionality"""
    
    @patch('core.server_manager.firestore_db')
    @patch('requests.get')
    def test_add_server_success(self, mock_requests_get, mock_firestore_db):
        """Test successful server addition"""
        from core.server_manager import ServerManager
        
        # Mock health check response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'status': 'healthy'}
        mock_response.elapsed.total_seconds.return_value = 0.5
        mock_requests_get.return_value = mock_response
        
        # Mock Firestore operations
        mock_firestore_db.db.collection.return_value.add.return_value = (None, MagicMock(id='new-server-id'))
        
        server_manager = ServerManager()
        server_manager.get_all_servers = MagicMock(return_value=[])  # No existing servers
        
        result = server_manager.add_server(
            server_name='test-server',
            server_url='https://api.test-server.com',
            server_type='processing',
            description='Test server'
        )
        
        assert result['success'] == True
        assert result['server']['name'] == 'test-server'
        assert result['server']['url'] == 'https://api.test-server.com'
        assert result['server']['status'] == 'active'
    
    def test_add_server_invalid_url(self):
        """Test server addition with invalid URL"""
        from core.server_manager import ServerManager
        
        server_manager = ServerManager()
        
        result = server_manager.add_server(
            server_name='test-server',
            server_url='invalid-url'
        )
        
        assert result['success'] == False
        assert 'must start with http://' in result['error']
    
    @patch('requests.get')
    def test_check_server_health_success(self, mock_requests_get):
        """Test successful server health check"""
        from core.server_manager import ServerManager
        
        # Mock successful response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'status': 'healthy'}
        mock_response.elapsed.total_seconds.return_value = 0.3
        mock_requests_get.return_value = mock_response
        
        server_manager = ServerManager()
        
        result = server_manager._check_server_health('https://api.test-server.com')
        
        assert result['healthy'] == True
        assert result['response_time'] == 0.3
        assert result['status_code'] == 200
    
    @patch('requests.get')
    def test_check_server_health_timeout(self, mock_requests_get):
        """Test server health check timeout"""
        from core.server_manager import ServerManager
        import requests
        
        # Mock timeout exception
        mock_requests_get.side_effect = requests.exceptions.Timeout()
        
        server_manager = ServerManager()
        
        result = server_manager._check_server_health('https://api.test-server.com')
        
        assert result['healthy'] == False
        assert result['error'] == 'Connection timeout'

class TestPushNotificationService:
    """Test push notification service"""
    
    @patch('core.push_notification_service.firestore_db')
    def test_send_notification_success(self, mock_firestore_db):
        """Test successful notification sending"""
        from core.push_notification_service import PushNotificationService
        
        # Mock Firestore operations
        mock_firestore_db.db.collection.return_value.add.return_value = (None, MagicMock(id='notification-id'))
        mock_firestore_db.db.collection.return_value.get.return_value.__len__ = MagicMock(return_value=5)
        
        push_service = PushNotificationService()
        
        result = push_service.send_notification_to_user(
            user_id='test-user-id',
            title='Test Notification',
            body='This is a test notification',
            data={'key': 'value'}
        )
        
        assert result == True
    
    @patch('core.push_notification_service.firestore_db')
    def test_send_test_notification(self, mock_firestore_db):
        """Test sending test notification"""
        from core.push_notification_service import PushNotificationService
        
        # Mock Firestore and database operations
        mock_firestore_db.get_all_video_tasks.return_value = [
            {'user_id': 'user1'},
            {'user_id': 'user2'}
        ]
        mock_firestore_db.db.collection.return_value.add.return_value = (None, MagicMock(id='notification-id'))
        mock_firestore_db.db.collection.return_value.get.return_value.__len__ = MagicMock(return_value=1)
        
        push_service = PushNotificationService()
        
        result = push_service.send_test_notification('simple')
        
        assert result['success'] == True
        assert 'Test Notification' in result['title']
        assert 'test push notification' in result['body']

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
