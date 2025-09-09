import os
import functools
from flask import request, jsonify, g
import firebase_admin
from firebase_admin import auth
from dotenv import load_dotenv

# Fallback imports for JWKS-based verification (no ADC required)
import json
import time
import requests
import jwt
from jwt.algorithms import RSAAlgorithm

# Import custom token manager
from .custom_auth import custom_token_manager

load_dotenv()

# Super admin configuration
SUPER_ADMINS = ['ouday.khaled@gmail.com', 'appsaawt@gmail.com']

_jwks_cache = {
    'keys': None,
    'fetched_at': 0,
}

def _get_firebase_project_id():
    return os.getenv('FIREBASE_PROJECT_ID') or os.getenv('GOOGLE_CLOUD_PROJECT') or 'thakii-973e3'

def _fetch_jwks():
    # Firebase JWKS endpoint
    url = 'https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com'
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json()

def _get_jwks_cached():
    # Cache for 1 hour
    if _jwks_cache['keys'] and (time.time() - _jwks_cache['fetched_at'] < 3600):
        return _jwks_cache['keys']
    jwks = _fetch_jwks()
    _jwks_cache['keys'] = jwks
    _jwks_cache['fetched_at'] = time.time()
    return jwks

def _verify_with_jwks(token: str):
    project_id = _get_firebase_project_id()
    jwks = _get_jwks_cached()
    headers = jwt.get_unverified_header(token)
    kid = headers.get('kid')
    if not kid:
        raise ValueError('Token header missing kid')

    key = None
    for k in jwks.get('keys', []):
        if k.get('kid') == kid:
            key = RSAAlgorithm.from_jwk(json.dumps(k))
            break
    if not key:
        # Refresh JWKS once if key not found
        _jwks_cache['keys'] = None
        jwks = _get_jwks_cached()
        for k in jwks.get('keys', []):
            if k.get('kid') == kid:
                key = RSAAlgorithm.from_jwk(json.dumps(k))
                break
    if not key:
        raise ValueError('Unable to find matching JWKS key')

    issuer = f"https://securetoken.google.com/{project_id}"
    decoded = jwt.decode(
        token,
        key=key,
        algorithms=['RS256'],
        audience=project_id,
        issuer=issuer,
        options={'verify_exp': True}
    )
    return decoded

def verify_auth_token():
    """Verify authentication token (Firebase or Custom) from Authorization header"""
    auth_header = request.headers.get('Authorization')
    
    if not auth_header:
        return None, "No Authorization header provided"
    
    try:
        # Extract token from "Bearer <token>" format
        if auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
        else:
            return None, "Invalid Authorization header format"

        # Check if it's a custom backend token first
        if custom_token_manager.is_custom_token(token):
            try:
                decoded_token = custom_token_manager.verify_custom_token(token)
                # Add token type for downstream processing
                decoded_token['_token_type'] = 'custom'
                return decoded_token, None
            except Exception as custom_err:
                return None, f"Custom token verification failed: {str(custom_err)}"

        # If not custom token, try Firebase verification
        # Try Firebase Admin first (if initialized)
        try:
            if firebase_admin._apps:
                decoded_token = auth.verify_id_token(token)
                decoded_token['_token_type'] = 'firebase'
                return decoded_token, None
        except Exception as primary_err:
            # Fallback to JWKS-based verification (does not require ADC)
            try:
                decoded_token = _verify_with_jwks(token)
                decoded_token['_token_type'] = 'firebase'
                return decoded_token, None
            except Exception as fallback_err:
                return None, f"Firebase token verification failed: {str(fallback_err)}"

        # If no Firebase app is initialized, use JWKS fallback
        decoded_token = _verify_with_jwks(token)
        decoded_token['_token_type'] = 'firebase'
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
        # Handle both Firebase and Custom token formats
        token_type = token_data.get('_token_type', 'firebase')
        
        if token_type == 'custom':
            # Custom token format
            user_info = custom_token_manager.extract_user_info(token_data)
            g.current_user = user_info
        else:
            # Firebase token format (uid/user_id/sub)
            uid = token_data.get('uid') or token_data.get('user_id') or token_data.get('sub')
            g.current_user = {
                'uid': uid,
                'email': token_data.get('email'),
                'name': token_data.get('name', token_data.get('email', '').split('@')[0] if token_data.get('email') else 'Unknown'),
                'picture': token_data.get('picture'),
                'email_verified': token_data.get('email_verified', False),
                'is_admin': token_data.get('email') in SUPER_ADMINS if token_data.get('email') else False,
                'firebase_provider': token_data.get('firebase', {}).get('sign_in_provider') if isinstance(token_data.get('firebase'), dict) else None,
                'auth_time': token_data.get('auth_time'),
                'token_type': token_type
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
        
        # Handle both Firebase and Custom token formats for admin check
        token_type = token_data.get('_token_type', 'firebase')
        
        if token_type == 'custom':
            # Custom token already has is_admin flag
            is_admin = token_data.get('is_admin', False)
            user_email = token_data.get('email')
        else:
            # Firebase token - check email against admin list
            user_email = token_data.get('email')
            is_admin = user_email in SUPER_ADMINS if user_email else False
        
        if not is_admin:
            return jsonify({"error": "Admin access required", "message": "Insufficient privileges"}), 403
        
        # Store user information in Flask's g object
        if token_type == 'custom':
            user_info = custom_token_manager.extract_user_info(token_data)
            g.current_user = user_info
        else:
            uid = token_data.get('uid') or token_data.get('user_id') or token_data.get('sub')
            g.current_user = {
                'uid': uid,
                'email': user_email,
                'name': token_data.get('name', user_email.split('@')[0] if user_email else 'Unknown'),
                'picture': token_data.get('picture'),
                'email_verified': token_data.get('email_verified', False),
                'is_admin': True,
                'firebase_provider': token_data.get('firebase', {}).get('sign_in_provider') if isinstance(token_data.get('firebase'), dict) else None,
                'auth_time': token_data.get('auth_time'),
                'token_type': token_type
            }
        
        return f(*args, **kwargs)
    
    return decorated_function

def get_current_user():
    """Get current authenticated user from Flask's g object"""
    return getattr(g, 'current_user', None)

def is_super_admin(email):
    """Check if email is a super admin"""
    return email in SUPER_ADMINS