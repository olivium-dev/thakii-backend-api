import os
import functools
from flask import request, jsonify, g
import firebase_admin
from firebase_admin import auth
from dotenv import load_dotenv

load_dotenv()

# Super admin configuration
SUPER_ADMINS = ['ouday.khaled@gmail.com', 'appsaawt@gmail.com']

def verify_auth_token():
    """Verify Firebase authentication token from Authorization header"""
    auth_header = request.headers.get('Authorization')
    
    if not auth_header:
        return None, "No Authorization header provided"
    
    try:
        # Extract token from "Bearer <token>" format
        if auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
        else:
            return None, "Invalid Authorization header format"
        
        # Verify the token with Firebase Admin SDK
        decoded_token = auth.verify_id_token(token)
        return decoded_token, None
        
    except Exception as e:
        return None, f"Token verification failed: {str(e)}"

def require_auth(f):
    """Decorator to require authentication for endpoints"""
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        token_data, error = verify_auth_token()
        
        if error:
            return jsonify({"error": "Authentication required", "message": error}), 401
        
        # Store user information in Flask's g object for use in the request
        g.current_user = {
            'uid': token_data['uid'],
            'email': token_data.get('email'),
            'email_verified': token_data.get('email_verified', False)
        }
        
        return f(*args, **kwargs)
    
    return decorated_function

def require_admin(f):
    """Decorator to require admin privileges for endpoints"""
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        token_data, error = verify_auth_token()
        
        if error:
            return jsonify({"error": "Authentication required", "message": error}), 401
        
        user_email = token_data.get('email')
        
        if not user_email or user_email not in SUPER_ADMINS:
            return jsonify({"error": "Admin access required", "message": "Insufficient privileges"}), 403
        
        # Store user information in Flask's g object
        g.current_user = {
            'uid': token_data['uid'],
            'email': user_email,
            'email_verified': token_data.get('email_verified', False),
            'is_admin': True
        }
        
        return f(*args, **kwargs)
    
    return decorated_function

def get_current_user():
    """Get current authenticated user from Flask's g object"""
    return getattr(g, 'current_user', None)

def is_super_admin(email):
    """Check if email is a super admin"""
    return email in SUPER_ADMINS