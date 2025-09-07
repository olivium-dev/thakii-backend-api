#!/usr/bin/env python3
"""
AWS Lambda handler for Thakii Backend API
Wraps the Flask application for serverless deployment
"""
import json
import base64
import io
import sys
import os
from urllib.parse import unquote_plus

# Import the Flask app
from app import app

def lambda_handler(event, context):
    """
    AWS Lambda handler that converts Lambda events to WSGI and back
    Supports both API Gateway v1 and v2 formats, ALB, and direct invocation
    """
    
    # Debug logging
    print(f"Event: {json.dumps(event, default=str)}")
    print(f"Context: {context}")
    
    try:
        # Handle different event formats
        if 'version' in event and event['version'] == '2.0':
            # API Gateway v2 format
            method = event['requestContext']['http']['method']
            path = event['rawPath']
            headers = event.get('headers', {})
            query_params = event.get('queryStringParameters') or {}
            body = event.get('body', '')
            is_base64 = event.get('isBase64Encoded', False)
            
        elif 'httpMethod' in event:
            # API Gateway v1 format
            method = event['httpMethod']
            path = event['path']
            headers = event.get('headers', {})
            query_params = event.get('queryStringParameters') or {}
            body = event.get('body', '')
            is_base64 = event.get('isBase64Encoded', False)
            
        elif 'requestContext' in event and 'elb' in event['requestContext']:
            # Application Load Balancer format
            method = event['httpMethod']
            path = event['path']
            headers = event.get('headers', {})
            query_params = event.get('queryStringParameters') or {}
            body = event.get('body', '')
            is_base64 = event.get('isBase64Encoded', False)
            
        else:
            # Direct invocation or test format
            method = event.get('httpMethod', event.get('method', 'GET'))
            path = event.get('path', '/')
            headers = event.get('headers', {})
            query_params = event.get('queryStringParameters', event.get('queryParams', {}))
            body = event.get('body', '')
            is_base64 = event.get('isBase64Encoded', False)

        # Handle base64 encoded body
        if is_base64 and body:
            try:
                body = base64.b64decode(body).decode('utf-8')
            except Exception as e:
                print(f"Error decoding base64 body: {e}")
                body = ''

        # Build query string
        query_string = ''
        if query_params:
            query_string = '&'.join([f'{k}={v}' for k, v in query_params.items()])

        # Create WSGI environ dictionary
        environ = {
            'REQUEST_METHOD': method,
            'SCRIPT_NAME': '',
            'PATH_INFO': unquote_plus(path),
            'QUERY_STRING': query_string,
            'CONTENT_TYPE': headers.get('content-type', headers.get('Content-Type', '')),
            'CONTENT_LENGTH': str(len(body.encode('utf-8'))) if body else '0',
            'SERVER_NAME': headers.get('host', headers.get('Host', 'localhost')).split(':')[0],
            'SERVER_PORT': headers.get('x-forwarded-port', '443'),
            'wsgi.version': (1, 0),
            'wsgi.url_scheme': headers.get('x-forwarded-proto', 'https'),
            'wsgi.input': io.BytesIO(body.encode('utf-8') if body else b''),
            'wsgi.errors': sys.stderr,
            'wsgi.multithread': False,
            'wsgi.multiprocess': False,
            'wsgi.run_once': False,
        }

        # Add headers to environ
        for key, value in headers.items():
            key = key.upper().replace('-', '_')
            if key not in ('CONTENT_TYPE', 'CONTENT_LENGTH'):
                environ[f'HTTP_{key}'] = value

        # Add Lambda-specific environ variables
        environ['lambda.context'] = context
        environ['lambda.event'] = event

        # Capture response
        response_data = {'statusCode': 500, 'headers': {}, 'body': ''}

        def start_response(status, response_headers, exc_info=None):
            response_data['statusCode'] = int(status.split()[0])
            response_data['headers'] = {}
            for header_name, header_value in response_headers:
                response_data['headers'][header_name] = header_value

        # Execute the Flask application
        try:
            app_response = app(environ, start_response)
            response_body = b''.join(app_response).decode('utf-8')
            response_data['body'] = response_body
            
        except Exception as e:
            print(f"Error executing Flask app: {e}")
            import traceback
            traceback.print_exc()
            response_data = {
                'statusCode': 500,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({
                    'error': 'Internal server error',
                    'message': str(e),
                    'type': 'lambda_handler_error'
                })
            }

        # Ensure CORS headers are present
        if 'Access-Control-Allow-Origin' not in response_data['headers']:
            response_data['headers']['Access-Control-Allow-Origin'] = '*'
        if 'Access-Control-Allow-Methods' not in response_data['headers']:
            response_data['headers']['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        if 'Access-Control-Allow-Headers' not in response_data['headers']:
            response_data['headers']['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'

        # Handle OPTIONS requests for CORS preflight
        if method == 'OPTIONS':
            response_data['statusCode'] = 200
            response_data['body'] = ''

        print(f"Response: {response_data}")
        return response_data

    except Exception as e:
        print(f"Lambda handler error: {e}")
        import traceback
        traceback.print_exc()
        
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': 'Lambda handler error',
                'message': str(e),
                'type': 'lambda_handler_exception'
            })
        }

# For local testing
if __name__ == '__main__':
    # Test the handler locally
    test_event = {
        'httpMethod': 'GET',
        'path': '/health',
        'headers': {},
        'queryStringParameters': None,
        'body': None,
        'isBase64Encoded': False
    }
    
    class MockContext:
        def __init__(self):
            self.function_name = 'test-function'
            self.function_version = '1'
            self.invoked_function_arn = 'arn:aws:lambda:us-east-1:123456789012:function:test'
            self.memory_limit_in_mb = 128
            self.remaining_time_in_millis = 30000
            self.log_group_name = '/aws/lambda/test'
            self.log_stream_name = '2023/01/01/[$LATEST]test'
            self.aws_request_id = 'test-request-id'
    
    result = lambda_handler(test_event, MockContext())
    print(json.dumps(result, indent=2))
