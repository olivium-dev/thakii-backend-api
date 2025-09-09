"""
Mock Token Endpoints for Testing
Add these to app.py after the exchange-token endpoint
"""

@app.route("/auth/mock-admin-token", methods=["POST"])
def generate_mock_admin_token():
    """Generate a mock admin token for testing purposes"""
    try:
        mock_admin_data = {
            'uid': 'mock-admin-user-id',
            'user_id': 'mock-admin-user-id',
            'email': 'mock.admin@thakii.test',
            'name': 'Mock Admin User',
            'picture': 'https://via.placeholder.com/96x96/4F46E5/FFFFFF?text=MA',
            'email_verified': True,
            'firebase': {'sign_in_provider': 'mock'},
            'auth_time': int(datetime.datetime.now().timestamp())
        }
        
        custom_token = custom_token_manager.generate_custom_token(mock_admin_data)
        
        return jsonify({
            "success": True,
            "message": "Mock admin token generated successfully",
            "custom_token": custom_token,
            "expires_in_hours": 72,
            "user": {
                'uid': mock_admin_data['uid'],
                'email': mock_admin_data['email'],
                'name': mock_admin_data['name'],
                'picture': mock_admin_data['picture'],
                'is_admin': True,
                'mock': True
            },
            "token_type": "custom_backend",
            "note": "Mock admin token for API testing"
        }), 200
        
    except Exception as e:
        return jsonify({"error": "Mock token generation failed", "message": str(e)}), 500

@app.route("/auth/mock-user-token", methods=["POST"])
def generate_mock_user_token():
    """Generate a mock regular user token for testing purposes"""
    try:
        mock_user_data = {
            'uid': 'mock-regular-user-id',
            'user_id': 'mock-regular-user-id',
            'email': 'mock.user@thakii.test',
            'name': 'Mock Regular User',
            'picture': 'https://via.placeholder.com/96x96/10B981/FFFFFF?text=MU',
            'email_verified': True,
            'firebase': {'sign_in_provider': 'mock'},
            'auth_time': int(datetime.datetime.now().timestamp())
        }
        
        custom_token = custom_token_manager.generate_custom_token(mock_user_data)
        
        return jsonify({
            "success": True,
            "message": "Mock user token generated successfully",
            "custom_token": custom_token,
            "expires_in_hours": 72,
            "user": {
                'uid': mock_user_data['uid'],
                'email': mock_user_data['email'],
                'name': mock_user_data['name'],
                'picture': mock_user_data['picture'],
                'is_admin': False,
                'mock': True
            },
            "token_type": "custom_backend",
            "note": "Mock user token for API testing"
        }), 200
        
    except Exception as e:
        return jsonify({"error": "Mock token generation failed", "message": str(e)}), 500
