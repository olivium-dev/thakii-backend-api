"""
AWS Lambda handler for Flask app - Simplified version without Firebase
This version demonstrates the API working on Lambda without external dependencies
"""
import json
import base64
import io
import sys
import os
from datetime import datetime

def lambda_handler(event, context):
    """AWS Lambda handler for Flask app - Simplified Demo Version"""
    
    # Handle ALB/API Gateway events
    if 'httpMethod' in event:
        # API Gateway format
        method = event['httpMethod']
        path = event['path']
        headers = event.get('headers', {})
        query_params = event.get('queryStringParameters') or {}
        body = event.get('body', '')
        
        # Handle base64 encoded body
        if event.get('isBase64Encoded', False):
            body = base64.b64decode(body).decode('utf-8')
            
    else:
        # Direct invocation format
        method = event.get('method', 'GET')
        path = event.get('path', '/')
        headers = event.get('headers', {})
        query_params = event.get('queryParams', {})
        body = event.get('body', '')

    # Simple routing for demonstration
    if path == '/health' or path == '/prod/health':
        return handle_health()
    elif path == '/demo' or path == '/prod/demo':
        return handle_demo()
    elif path.startswith('/admin') and method == 'GET':
        return handle_admin_demo()
    elif path == '/upload' or path == '/prod/upload':
        return handle_upload_demo(method)
    else:
        return handle_not_found(path)

def handle_health():
    """Health check endpoint"""
    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization'
        },
        'body': json.dumps({
            'service': 'Thakii Lecture2PDF Service',
            'status': 'healthy',
            'version': '1.0.0',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'environment': 'AWS Lambda',
            'region': os.environ.get('AWS_REGION', 'us-east-2'),
            'function_name': os.environ.get('AWS_LAMBDA_FUNCTION_NAME', 'thakii-backend-api'),
            'memory_size': os.environ.get('AWS_LAMBDA_FUNCTION_MEMORY_SIZE', '1024'),
            'runtime': 'Python 3.10',
            'deployment': 'Successful ✅'
        }),
        'isBase64Encoded': False
    }

def handle_demo():
    """Demo endpoint showing API capabilities"""
    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization'
        },
        'body': json.dumps({
            'message': 'Thakii Backend API Demo',
            'description': 'This is a simplified demo version running on AWS Lambda',
            'features': [
                'Video upload processing',
                'PDF generation from lectures',
                'Subtitle extraction',
                'User authentication',
                'Admin management',
                'Real-time notifications'
            ],
            'endpoints': {
                'health': 'GET /health - Service health check',
                'demo': 'GET /demo - This demo endpoint',
                'upload': 'POST /upload - Video upload (demo)',
                'admin': 'GET /admin/* - Admin endpoints (demo)'
            },
            'infrastructure': {
                'platform': 'AWS Lambda',
                'api_gateway': 'Configured ✅',
                's3_storage': 'Ready ✅',
                'iam_roles': 'Configured ✅',
                'monitoring': 'CloudWatch ✅'
            },
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }),
        'isBase64Encoded': False
    }

def handle_admin_demo():
    """Demo admin endpoint"""
    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization'
        },
        'body': json.dumps({
            'admin_panel': 'Demo Mode',
            'message': 'Admin functionality available',
            'stats': {
                'total_videos': 1247,
                'processed_today': 23,
                'active_users': 156,
                'storage_used': '2.3 GB',
                'success_rate': '98.5%'
            },
            'recent_activity': [
                {'time': '14:25', 'action': 'Video processed', 'user': 'user123'},
                {'time': '14:20', 'action': 'New upload', 'user': 'user456'},
                {'time': '14:15', 'action': 'PDF generated', 'user': 'user789'}
            ],
            'note': 'This is a demo version. Full functionality requires Firebase integration.',
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }),
        'isBase64Encoded': False
    }

def handle_upload_demo(method):
    """Demo upload endpoint"""
    if method == 'OPTIONS':
        return {
            'statusCode': 200,
            'headers': {
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'POST, OPTIONS',
                'Access-Control-Allow-Headers': 'Content-Type, Authorization'
            },
            'body': '',
            'isBase64Encoded': False
        }
    
    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization'
        },
        'body': json.dumps({
            'message': 'Upload endpoint demo',
            'status': 'Demo mode - upload simulation',
            'upload_info': {
                'max_file_size': '500MB',
                'supported_formats': ['mp4', 'avi', 'mov', 'mkv'],
                'processing_time': '5-15 minutes',
                'output_formats': ['PDF', 'SRT subtitles']
            },
            'demo_response': {
                'video_id': 'demo-12345',
                'status': 'queued',
                'estimated_completion': '10 minutes',
                'message': 'Video queued for processing'
            },
            'note': 'This is a demo. Real uploads require authentication and Firebase integration.',
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }),
        'isBase64Encoded': False
    }

def handle_not_found(path):
    """Handle 404 not found"""
    return {
        'statusCode': 404,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps({
            'error': 'Not Found',
            'message': f'Endpoint {path} not found',
            'available_endpoints': [
                '/health - Service health check',
                '/demo - API demonstration',
                '/admin/* - Admin endpoints (demo)',
                '/upload - Upload endpoint (demo)'
            ],
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }),
        'isBase64Encoded': False
    }
