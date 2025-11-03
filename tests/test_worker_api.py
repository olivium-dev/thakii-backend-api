#!/usr/bin/env python3
"""
Tests for Worker API endpoints
"""

import os
import sys
import unittest
import json
import datetime
from unittest.mock import patch, MagicMock

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the app
from app import app, worker_task_manager

class TestWorkerAPI(unittest.TestCase):
    def setUp(self):
        # Configure app for testing
        app.config['TESTING'] = True
        self.client = app.test_client()
        
        # Enable worker API for testing
        worker_task_manager.is_enabled = True
        
        # Mock the postgres_db connection
        self.postgres_db_patcher = patch('app.postgres_db')
        self.mock_postgres_db = self.postgres_db_patcher.start()
        
        # Set up mock task data
        self.mock_task = {
            'video_id': 'test-video-id',
            'filename': 'test.mp4',
            's3_key': 'videos/test-video-id.mp4',
            'user_id': 'test-user-id',
            'user_email': 'test@example.com',
            'status': 'in_queue',
            'created_at': datetime.datetime.now().isoformat(),
            'updated_at': datetime.datetime.now().isoformat()
        }
    
    def tearDown(self):
        # Stop all patches
        self.postgres_db_patcher.stop()
    
    def test_pickup_task_success(self):
        # Mock worker_task_manager.pickup_task to return a task
        worker_task_manager.pickup_task = MagicMock(return_value=self.mock_task)
        
        # Call the endpoint
        response = self.client.post('/internal/worker/pickup-task', 
                                   json={'worker_id': 'test-worker-id'})
        
        # Verify response
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['success'])
        self.assertEqual(data['task']['video_id'], 'test-video-id')
        
        # Verify worker_task_manager.pickup_task was called
        worker_task_manager.pickup_task.assert_called_once_with('test-worker-id', 4)
    
    def test_pickup_task_no_tasks(self):
        # Mock worker_task_manager.pickup_task to return None
        worker_task_manager.pickup_task = MagicMock(return_value=None)
        
        # Call the endpoint
        response = self.client.post('/internal/worker/pickup-task', 
                                   json={'worker_id': 'test-worker-id'})
        
        # Verify response
        self.assertEqual(response.status_code, 204)
        
        # Verify worker_task_manager.pickup_task was called
        worker_task_manager.pickup_task.assert_called_once()
    
    def test_pickup_task_missing_worker_id(self):
        # Call the endpoint without worker_id
        response = self.client.post('/internal/worker/pickup-task', json={})
        
        # Verify response
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn('error', data)
    
    def test_update_task_success(self):
        # Mock worker_task_manager.update_task to return True
        worker_task_manager.update_task = MagicMock(return_value=True)
        
        # Mock postgres_db.get_video_task to return a task
        self.mock_postgres_db.get_video_task.return_value = self.mock_task
        
        # Call the endpoint
        response = self.client.post('/internal/worker/update-task', json={
            'video_id': 'test-video-id',
            'worker_id': 'test-worker-id',
            'status': 'completed',
            'progress': 100,
            'pdf_url': 'https://example.com/test.pdf'
        })
        
        # Verify response
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['success'])
        
        # Verify worker_task_manager.update_task was called
        worker_task_manager.update_task.assert_called_once_with(
            video_id='test-video-id',
            worker_id='test-worker-id',
            status='completed',
            progress=100,
            pdf_url='https://example.com/test.pdf',
            error_message=None
        )
    
    def test_update_task_failure(self):
        # Mock worker_task_manager.update_task to return False
        worker_task_manager.update_task = MagicMock(return_value=False)
        
        # Call the endpoint
        response = self.client.post('/internal/worker/update-task', json={
            'video_id': 'test-video-id',
            'worker_id': 'test-worker-id',
            'status': 'failed',
            'error_message': 'Test error'
        })
        
        # Verify response
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn('error', data)
        
        # Verify worker_task_manager.update_task was called
        worker_task_manager.update_task.assert_called_once()
    
    def test_update_task_missing_fields(self):
        # Call the endpoint without required fields
        response = self.client.post('/internal/worker/update-task', json={
            'video_id': 'test-video-id'
        })
        
        # Verify response
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn('error', data)
    
    def test_heartbeat_success(self):
        # Mock worker_task_manager.worker_heartbeat to return True
        worker_task_manager.worker_heartbeat = MagicMock(return_value=True)
        
        # Call the endpoint
        response = self.client.post('/internal/worker/heartbeat', json={
            'worker_id': 'test-worker-id',
            'active_tasks': ['test-video-id-1', 'test-video-id-2']
        })
        
        # Verify response
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['success'])
        
        # Verify worker_task_manager.worker_heartbeat was called
        worker_task_manager.worker_heartbeat.assert_called_once_with(
            'test-worker-id', ['test-video-id-1', 'test-video-id-2']
        )
    
    def test_heartbeat_missing_worker_id(self):
        # Call the endpoint without worker_id
        response = self.client.post('/internal/worker/heartbeat', json={})
        
        # Verify response
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn('error', data)
    
    def test_recover_stale_tasks_success(self):
        # Mock worker_task_manager.recover_stale_tasks to return 2
        worker_task_manager.recover_stale_tasks = MagicMock(return_value=2)
        
        # Mock os.getenv to return the correct admin key
        with patch('os.getenv', return_value='test-admin-key'):
            # Call the endpoint with correct admin key
            response = self.client.post('/internal/worker/recover-stale-tasks',
                                      headers={'X-Admin-Key': 'test-admin-key'})
            
            # Verify response
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.data)
            self.assertTrue(data['success'])
            self.assertEqual(data['recovered_count'], 2)
            
            # Verify worker_task_manager.recover_stale_tasks was called
            worker_task_manager.recover_stale_tasks.assert_called_once()
    
    def test_recover_stale_tasks_unauthorized(self):
        # Call the endpoint without admin key
        response = self.client.post('/internal/worker/recover-stale-tasks')
        
        # Verify response
        self.assertEqual(response.status_code, 401)
        data = json.loads(response.data)
        self.assertIn('error', data)

if __name__ == '__main__':
    unittest.main()
