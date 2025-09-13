#!/usr/bin/env python3
"""
Unit tests for the main Flask application
Tests all endpoints and core functionality
"""
import pytest
import json
import tempfile
import os
from unittest.mock import Mock, patch, MagicMock
import sys
import io

# Add the parent directory to the path to import the app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from core.auth_middleware import is_super_admin

class TestApp:
    """Test suite for the main Flask application"""
    
    @pytest.fixture
    def client(self):
        """Create a test client"""
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        with app.test_client() as client:
            yield client
    
    @pytest.fixture
    def mock_firebase_disabled(self):
        """Mock Firebase as disabled for testing"""
        with patch.dict(os.environ, {'DISABLE_FIREBASE': 'true'}):
            yield
    
    def test_health_endpoint(self, client):
        """Test the health check endpoint"""
        response = client.get('/health')
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert data['service'] == 'Thakii Lecture2PDF Service'
        assert data['status'] == 'healthy'
        assert data['database'] == 'Firestore'
        assert data['storage'] == 'S3'
        assert 'timestamp' in data
    
    def test_upload_endpoint_no_auth(self, client):
        """Test upload endpoint without authentication"""
        response = client.post('/upload')
        assert response.status_code == 401
        
        data = json.loads(response.data)
        assert 'error' in data
        assert data['error'] == 'Authentication required'
    
    def test_upload_endpoint_no_file(self, client, mock_firebase_disabled):
        """Test upload endpoint without file"""
        with patch('core.auth_middleware.verify_auth_token') as mock_verify:
            mock_verify.return_value = ({'uid': 'test-uid', 'email': 'test@example.com'}, None)
            
            response = client.post('/upload')
            assert response.status_code == 400
            
            data = json.loads(response.data)
            assert data['error'] == 'No file provided'
    
    def test_upload_endpoint_empty_filename(self, client, mock_firebase_disabled):
        """Test upload endpoint with empty filename"""
        with patch('core.auth_middleware.verify_auth_token') as mock_verify:
            mock_verify.return_value = ({'uid': 'test-uid', 'email': 'test@example.com'}, None)
            
            data = {'file': (io.BytesIO(b'fake video content'), '')}
            response = client.post('/upload', data=data, content_type='multipart/form-data')
            assert response.status_code == 400
            
            response_data = json.loads(response.data)
            assert response_data['error'] == 'No selected file'
    
    @patch('core.s3_storage.S3Storage.upload_video')
    @patch('core.firestore_db.firestore_db.create_video_task')
    def test_upload_endpoint_success(self, mock_create_task, mock_upload, client, mock_firebase_disabled):
        """Test successful file upload"""
        with patch('core.auth_middleware.verify_auth_token') as mock_verify:
            mock_verify.return_value = ({'uid': 'test-uid', 'email': 'test@example.com'}, None)
            mock_upload.return_value = 'videos/test-id/test.mp4'
            mock_create_task.return_value = {'video_id': 'test-id'}
            
            data = {'file': (io.BytesIO(b'fake video content'), 'test.mp4')}
            response = client.post('/upload', data=data, content_type='multipart/form-data')
            assert response.status_code == 200
            
            response_data = json.loads(response.data)
            assert 'video_id' in response_data
            assert 'message' in response_data
            assert 's3_key' in response_data
    
    def test_list_endpoint_no_auth(self, client):
        """Test list endpoint without authentication"""
        response = client.get('/list')
        assert response.status_code == 401
    
    @patch('core.firestore_db.firestore_db.get_user_video_tasks')
    def test_list_endpoint_user(self, mock_get_tasks, client, mock_firebase_disabled):
        """Test list endpoint for regular user"""
        with patch('core.auth_middleware.verify_auth_token') as mock_verify:
            mock_verify.return_value = ({'uid': 'test-uid', 'email': 'user@example.com'}, None)
            mock_get_tasks.return_value = [
                {
                    'id': 'test-id-1',
                    'filename': 'test1.mp4',
                    'status': 'done',
                    'created_at': '2024-01-01 10:00:00',
                    'user_email': 'user@example.com'
                }
            ]
            
            response = client.get('/list')
            assert response.status_code == 200
            
            data = json.loads(response.data)
            videos = data.get('videos', data)  # Handle both old and new response format
            assert len(videos) >= 1  # At least 1 video (may have more from real uploads)
            # Find our test video
            test_video = next((v for v in videos if v.get('id') == 'test-id-1'), None)
            assert test_video is not None
            assert test_video['video_name'] == 'test1.mp4'
    
    @patch('core.firestore_db.firestore_db.get_all_video_tasks')
    def test_list_endpoint_admin(self, mock_get_tasks, client, mock_firebase_disabled):
        """Test list endpoint for admin user"""
        with patch('core.auth_middleware.verify_auth_token') as mock_verify:
            mock_verify.return_value = ({'uid': 'admin-uid', 'email': 'ouday.khaled@gmail.com'}, None)
            mock_get_tasks.return_value = [
                {
                    'id': 'test-id-1',
                    'filename': 'test1.mp4',
                    'status': 'done',
                    'created_at': '2024-01-01 10:00:00',
                    'user_email': 'user1@example.com'
                },
                {
                    'id': 'test-id-2',
                    'filename': 'test2.mp4',
                    'status': 'in_progress',
                    'created_at': '2024-01-01 11:00:00',
                    'user_email': 'user2@example.com'
                }
            ]
            
            response = client.get('/list')
            assert response.status_code == 200
            
            data = json.loads(response.data)
            videos = data.get('videos', data)  # Handle both old and new response format
            assert len(videos) >= 2  # At least 2 videos (may have more from real uploads)
    
    def test_status_endpoint_no_auth(self, client):
        """Test status endpoint without authentication"""
        response = client.get('/status/test-id')
        assert response.status_code == 401
    
    @patch('core.firestore_db.firestore_db.get_video_task')
    def test_status_endpoint_not_found(self, mock_get_task, client, mock_firebase_disabled):
        """Test status endpoint for non-existent video"""
        with patch('core.auth_middleware.verify_auth_token') as mock_verify:
            mock_verify.return_value = ({'uid': 'test-uid', 'email': 'test@example.com'}, None)
            mock_get_task.return_value = None
            
            response = client.get('/status/non-existent-id')
            assert response.status_code == 404
            
            data = json.loads(response.data)
            assert data['error'] == 'Video not found'
    
    @patch('core.firestore_db.firestore_db.get_video_task')
    def test_status_endpoint_access_denied(self, mock_get_task, client, mock_firebase_disabled):
        """Test status endpoint with access denied"""
        with patch('core.auth_middleware.verify_auth_token') as mock_verify:
            mock_verify.return_value = ({'uid': 'test-uid', 'email': 'test@example.com'}, None)
            mock_get_task.return_value = {
                'video_id': 'test-id',
                'user_id': 'other-uid',  # Different user
                'filename': 'test.mp4',
                'status': 'done'
            }
            
            response = client.get('/status/test-id')
            assert response.status_code == 403
            
            data = json.loads(response.data)
            assert data['error'] == 'Access denied'
    
    @patch('core.firestore_db.firestore_db.get_video_task')
    def test_status_endpoint_success(self, mock_get_task, client, mock_firebase_disabled):
        """Test successful status check"""
        with patch('core.auth_middleware.verify_auth_token') as mock_verify:
            mock_verify.return_value = ({'uid': 'test-uid', 'email': 'test@example.com'}, None)
            mock_get_task.return_value = {
                'video_id': 'test-id',
                'user_id': 'test-uid',
                'filename': 'test.mp4',
                'status': 'done',
                'created_at': '2024-01-01 10:00:00',
                'user_email': 'test@example.com'
            }
            
            response = client.get('/status/test-id')
            assert response.status_code == 200
            
            data = json.loads(response.data)
            assert data['video_id'] == 'test-id'
            assert data['filename'] == 'test.mp4'
            assert data['status'] == 'done'
    
    def test_download_endpoint_no_auth(self, client):
        """Test download endpoint without authentication"""
        response = client.get('/download/test-id')
        assert response.status_code == 401
    
    @patch('core.firestore_db.firestore_db.get_video_task')
    def test_download_endpoint_not_ready(self, mock_get_task, client, mock_firebase_disabled):
        """Test download endpoint when PDF is not ready"""
        with patch('core.auth_middleware.verify_auth_token') as mock_verify:
            mock_verify.return_value = ({'uid': 'test-uid', 'email': 'test@example.com'}, None)
            mock_get_task.return_value = {
                'video_id': 'test-id',
                'user_id': 'test-uid',
                'filename': 'test.mp4',
                'status': 'in_progress'  # Not done yet
            }
            
            response = client.get('/download/test-id')
            assert response.status_code == 400
            
            data = json.loads(response.data)
            assert data['error'] == 'PDF not ready yet'
    
    @patch('core.s3_storage.S3Storage.download_pdf')
    @patch('core.firestore_db.firestore_db.get_video_task')
    def test_download_endpoint_success(self, mock_get_task, mock_download, client, mock_firebase_disabled):
        """Test successful download URL generation"""
        with patch('core.auth_middleware.verify_auth_token') as mock_verify:
            mock_verify.return_value = ({'uid': 'test-uid', 'email': 'test@example.com'}, None)
            mock_get_task.return_value = {
                'video_id': 'test-id',
                'user_id': 'test-uid',
                'filename': 'test.mp4',
                'status': 'done'
            }
            mock_download.return_value = 'https://s3.amazonaws.com/bucket/pdfs/test-id.pdf?expires=...'
            
            response = client.get('/download/test-id')
            assert response.status_code == 200
            
            data = json.loads(response.data)
            assert 'download_url' in data
            assert data['video_id'] == 'test-id'
            assert data['filename'] == 'test.mp4'
    
    def test_admin_endpoint_no_auth(self, client):
        """Test admin endpoint without authentication"""
        response = client.get('/admin/stats')
        assert response.status_code == 401
    
    def test_admin_endpoint_insufficient_privileges(self, client, mock_firebase_disabled):
        """Test admin endpoint with insufficient privileges"""
        with patch('core.auth_middleware.verify_auth_token') as mock_verify:
            mock_verify.return_value = ({'uid': 'test-uid', 'email': 'regular@user.com'}, None)
            
            response = client.get('/admin/stats')
            assert response.status_code == 403
            
            data = json.loads(response.data)
            assert data['error'] == 'Admin access required'
    
    @patch('core.firestore_db.firestore_db.get_admin_stats')
    def test_admin_stats_success(self, mock_get_stats, client, mock_firebase_disabled):
        """Test successful admin stats retrieval"""
        with patch('core.auth_middleware.verify_auth_token') as mock_verify:
            mock_verify.return_value = ({'uid': 'admin-uid', 'email': 'ouday.khaled@gmail.com'}, None)
            mock_get_stats.return_value = {
                'totalUsers': 10,
                'totalVideos': 25,
                'totalPDFs': 20,
                'activeProcessing': 3
            }
            
            response = client.get('/admin/stats')
            assert response.status_code == 200
            
            data = json.loads(response.data)
            assert data['totalUsers'] == 10
            assert data['totalVideos'] == 25
    
    def test_super_admin_check(self):
        """Test super admin email validation"""
        assert is_super_admin('ouday.khaled@gmail.com') == True
        assert is_super_admin('appsaawt@gmail.com') == True
        assert is_super_admin('regular@user.com') == False
        assert is_super_admin('') == False
        assert is_super_admin(None) == False

class TestLambdaHandler:
    """Test suite for the Lambda handler"""
    
    def test_lambda_handler_import(self):
        """Test that lambda handler can be imported"""
        from lambda_handler import lambda_handler
        assert callable(lambda_handler)
    
    @patch('lambda_handler.app')
    def test_lambda_handler_health_check(self, mock_app):
        """Test lambda handler with health check request"""
        from lambda_handler import lambda_handler
        
        # Mock Flask app response
        mock_app.return_value = [b'{"status": "healthy"}']
        
        def mock_start_response(status, headers, exc_info=None):
            pass
        
        mock_app.side_effect = lambda environ, start_response: (
            start_response('200 OK', [('Content-Type', 'application/json')]),
            [b'{"status": "healthy"}']
        )[1]
        
        event = {
            'httpMethod': 'GET',
            'path': '/health',
            'headers': {},
            'queryStringParameters': None,
            'body': None,
            'isBase64Encoded': False
        }
        
        class MockContext:
            function_name = 'test-function'
            aws_request_id = 'test-request-id'
        
        result = lambda_handler(event, MockContext())
        
        assert result['statusCode'] == 200
        assert 'body' in result
        assert 'headers' in result
    
    def test_lambda_handler_api_gateway_v2(self):
        """Test lambda handler with API Gateway v2 format"""
        from lambda_handler import lambda_handler
        
        event = {
            'version': '2.0',
            'requestContext': {
                'http': {
                    'method': 'GET'
                }
            },
            'rawPath': '/health',
            'headers': {},
            'queryStringParameters': None,
            'body': None,
            'isBase64Encoded': False
        }
        
        class MockContext:
            function_name = 'test-function'
            aws_request_id = 'test-request-id'
        
        with patch('lambda_handler.app') as mock_app:
            mock_app.return_value = [b'{"status": "healthy"}']
            result = lambda_handler(event, MockContext())
            assert 'statusCode' in result
    
    def test_lambda_handler_cors_headers(self):
        """Test that CORS headers are added"""
        from lambda_handler import lambda_handler
        
        event = {
            'httpMethod': 'OPTIONS',
            'path': '/upload',
            'headers': {},
            'queryStringParameters': None,
            'body': None,
            'isBase64Encoded': False
        }
        
        class MockContext:
            function_name = 'test-function'
            aws_request_id = 'test-request-id'
        
        result = lambda_handler(event, MockContext())
        
        assert result['statusCode'] == 200
        assert 'Access-Control-Allow-Origin' in result['headers']
        assert 'Access-Control-Allow-Methods' in result['headers']
        assert 'Access-Control-Allow-Headers' in result['headers']

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
