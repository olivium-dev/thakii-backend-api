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

        # Try Firebase Admin first (if initialized)
        try:
            if firebase_admin._apps:
                decoded_token = auth.verify_id_token(token)
                return decoded_token, None
        except Exception as primary_err:
            # Fallback to JWKS-based verification (does not require ADC)
            try:
                decoded_token = _verify_with_jwks(token)
                return decoded_token, None
            except Exception as fallback_err:
                return None, f"Token verification failed: {str(fallback_err)}"

        # If no Firebase app is initialized, use JWKS fallback
        decoded_token = _verify_with_jwks(token)
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