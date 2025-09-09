#!/usr/bin/env python3
"""
Fix the auth middleware test and deploy the backend with JWKS fallback
"""
import subprocess
import sys

def fix_test():
    """Fix the failing auth middleware test"""
    test_content = '''
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
        with app.test_request_context(headers={'Authorization': 'Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiIsImtpZCI6InRlc3Qta2V5In0.eyJ1aWQiOiJ0ZXN0LXVpZCIsImVtYWlsIjoidGVzdEBleGFtcGxlLmNvbSIsImVtYWlsX3ZlcmlmaWVkIjp0cnVlfQ.test-signature'}):
            result, error = verify_auth_token()
            assert error is None
            assert result['uid'] == 'test-uid'
            assert result['email'] == 'test@example.com'
    '''
    
    # Read the test file
    with open('tests/test_core_modules.py', 'r') as f:
        content = f.read()
    
    # Replace the failing test
    old_test = '''    def test_verify_auth_token_success(self):
        """Test successful token verification"""
        from core.auth_middleware import verify_auth_token
        from flask import Flask
        
        # Mock Firebase admin auth
        with patch('firebase_admin.auth.verify_id_token') as mock_verify:
            mock_verify.return_value = {
                'uid': 'test-uid',
                'email': 'test@example.com',
                'email_verified': True
            }
            
            app = Flask(__name__)
            with app.test_request_context(headers={'Authorization': 'Bearer valid-token'}):
                result, error = verify_auth_token()
                assert error is None
                assert result['uid'] == 'test-uid'
                assert result['email'] == 'test@example.com' '''
    
    if old_test in content:
        content = content.replace(old_test, test_content.strip())
        with open('tests/test_core_modules.py', 'w') as f:
            f.write(content)
        print("✅ Fixed test_verify_auth_token_success")
    else:
        print("⚠️ Could not find the exact test to replace")

def deploy_backend():
    """Deploy the backend with JWKS fallback"""
    deploy_script = '''#!/bin/bash
echo "🔄 Stopping existing backend..."
ssh -o ProxyCommand="cloudflared access ssh --hostname %h" ec2-user@vps-71.fds-1.com "pkill -f 'python3 app.py' || true"
sleep 3

echo "📥 Updating code..."
ssh -o ProxyCommand="cloudflared access ssh --hostname %h" ec2-user@vps-71.fds-1.com "cd thakii-backend-api && git fetch origin && git reset --hard origin/main && git pull origin main"

echo "🔧 Installing dependencies..."
ssh -o ProxyCommand="cloudflared access ssh --hostname %h" ec2-user@vps-71.fds-1.com "cd thakii-backend-api && source venv/bin/activate && pip install -r requirements.txt && pip install PyJWT requests"

echo "🔧 Configuring environment..."
ssh -o ProxyCommand="cloudflared access ssh --hostname %h" ec2-user@vps-71.fds-1.com 'cd thakii-backend-api && cat > .env << "ENVEOF"
# Flask Configuration
FLASK_ENV=production
FLASK_DEBUG=False
PORT=5001

# AWS Configuration
AWS_DEFAULT_REGION=us-east-2
S3_BUCKET_NAME=thakii-video-storage-1753883631

# Firebase Configuration (ENABLED with JWKS fallback)
GOOGLE_CLOUD_PROJECT=thakii-973e3
FIREBASE_PROJECT_ID=thakii-973e3

# CORS Configuration
ALLOWED_ORIGINS=https://thakii-frontend.netlify.app
ENVEOF'

echo "🚀 Starting backend..."
ssh -o ProxyCommand="cloudflared access ssh --hostname %h" ec2-user@vps-71.fds-1.com "cd thakii-backend-api && source venv/bin/activate && source .env && mkdir -p logs && nohup python3 app.py > logs/backend-jwks.log 2>&1 & echo \\$! > backend.pid"

echo "⏳ Waiting for startup..."
sleep 10

echo "🏥 Testing health..."
ssh -o ProxyCommand="cloudflared access ssh --hostname %h" ec2-user@vps-71.fds-1.com "curl -f http://127.0.0.1:5001/health || echo 'Health check failed'"

echo "🔐 Testing auth with invalid token..."
ssh -o ProxyCommand="cloudflared access ssh --hostname %h" ec2-user@vps-71.fds-1.com "curl -H 'Authorization: Bearer invalid-token' http://127.0.0.1:5001/list"

echo "✅ Deployment complete"
'''
    
    with open('deploy_backend_jwks.sh', 'w') as f:
        f.write(deploy_script)
    
    subprocess.run(['chmod', '+x', 'deploy_backend_jwks.sh'])
    print("✅ Created deploy_backend_jwks.sh")

if __name__ == '__main__':
    print("🔧 Fixing test and creating deployment script...")
    fix_test()
    deploy_backend()
    
    print("\n🚀 Next steps:")
    print("1. Commit and push the test fix:")
    print("   git add tests/test_core_modules.py")
    print("   git commit -m 'fix: update auth middleware test for JWKS fallback'")
    print("   git push origin main")
    print("\n2. Deploy the backend:")
    print("   ./deploy_backend_jwks.sh")
