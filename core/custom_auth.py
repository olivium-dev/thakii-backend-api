import os
import jwt
import time
import json
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()

# Custom token configuration
CUSTOM_TOKEN_SECRET = os.getenv('CUSTOM_TOKEN_SECRET', 'thakii-custom-secret-key-2025')
CUSTOM_TOKEN_ALGORITHM = 'HS256'
CUSTOM_TOKEN_ISSUER = 'thakii-backend'
CUSTOM_TOKEN_AUDIENCE = 'thakii-frontend'

# Token expiration: 72 hours
CUSTOM_TOKEN_EXPIRY_HOURS = 72

class CustomTokenManager:
    """Manages custom backend tokens with extended expiration"""
    
    @staticmethod
    def generate_custom_token(firebase_user_data: Dict[str, Any]) -> str:
        """
        Generate a custom backend token from Firebase user data
        
        Args:
            firebase_user_data: User data extracted from Firebase token
            
        Returns:
            Custom JWT token string
        """
        now = datetime.utcnow()
        expiry = now + timedelta(hours=CUSTOM_TOKEN_EXPIRY_HOURS)
        
        # Extract user information
        user_id = firebase_user_data.get('uid') or firebase_user_data.get('user_id') or firebase_user_data.get('sub')
        email = firebase_user_data.get('email')
        name = firebase_user_data.get('name', email.split('@')[0] if email else 'Unknown')
        picture = firebase_user_data.get('picture')
        email_verified = firebase_user_data.get('email_verified', False)
        
        # Create custom payload
        payload = {
            # Standard JWT claims
            'iss': CUSTOM_TOKEN_ISSUER,
            'aud': CUSTOM_TOKEN_AUDIENCE,
            'iat': int(now.timestamp()),
            'exp': int(expiry.timestamp()),
            'nbf': int(now.timestamp()),
            
            # Custom user claims
            'user_id': user_id,
            'email': email,
            'name': name,
            'picture': picture,
            'email_verified': email_verified,
            'token_type': 'custom_backend',
            'token_version': '1.0',
            
            # Admin status
            'is_admin': email in ['ouday.khaled@gmail.com', 'appsaawt@gmail.com'] if email else False,
            
            # Firebase metadata
            'firebase_provider': firebase_user_data.get('firebase', {}).get('sign_in_provider', 'unknown'),
            'auth_time': firebase_user_data.get('auth_time'),
            
            # Token fingerprint for security
            'token_hash': hashlib.sha256(f"{user_id}:{email}:{int(now.timestamp())}".encode()).hexdigest()[:16]
        }
        
        # Generate JWT token
        print(f"DEBUG: Generating token with secret: {CUSTOM_TOKEN_SECRET[:10]}...")
        print(f"DEBUG: Payload: {payload}")
        token = jwt.encode(payload, CUSTOM_TOKEN_SECRET, algorithm=CUSTOM_TOKEN_ALGORITHM)
        print(f"DEBUG: Generated token: {token[:50]}...")
        return token
    
    @staticmethod
    def verify_custom_token(token: str) -> Dict[str, Any]:
        """
        Verify and decode a custom backend token
        
        Args:
            token: Custom JWT token string
            
        Returns:
            Decoded token payload
            
        Raises:
            jwt.InvalidTokenError: If token is invalid
        """
        try:
            # Debug: Print token details
            print(f"DEBUG: Verifying token with secret: {CUSTOM_TOKEN_SECRET[:10]}...")
            print(f"DEBUG: Token: {token[:50]}...")
            
            payload = jwt.decode(
                token,
                CUSTOM_TOKEN_SECRET,
                algorithms=[CUSTOM_TOKEN_ALGORITHM],
                audience=CUSTOM_TOKEN_AUDIENCE,
                issuer=CUSTOM_TOKEN_ISSUER,
                options={
                    'verify_exp': True,
                    'verify_iat': True,
                    'verify_nbf': True,
                    'require': ['exp', 'iat', 'user_id', 'email']
                }
            )
            
            # Validate token type
            if payload.get('token_type') != 'custom_backend':
                raise jwt.InvalidTokenError('Invalid token type')
            
            print(f"DEBUG: Token verified successfully for user: {payload.get('email')}")
            return payload
            
        except jwt.ExpiredSignatureError:
            print("DEBUG: Token has expired")
            raise jwt.InvalidTokenError('Token has expired')
        except jwt.InvalidAudienceError:
            print("DEBUG: Invalid token audience")
            raise jwt.InvalidTokenError('Invalid token audience')
        except jwt.InvalidIssuerError:
            print("DEBUG: Invalid token issuer")
            raise jwt.InvalidTokenError('Invalid token issuer')
        except Exception as e:
            print(f"DEBUG: Token verification error: {str(e)}")
            raise jwt.InvalidTokenError(f'Token verification failed: {str(e)}')
    
    @staticmethod
    def is_custom_token(token: str) -> bool:
        """
        Check if a token is a custom backend token (without full verification)
        
        Args:
            token: JWT token string
            
        Returns:
            True if it's a custom token format
        """
        try:
            # Decode without verification to check token type
            unverified = jwt.decode(token, options={"verify_signature": False})
            return unverified.get('token_type') == 'custom_backend' and unverified.get('iss') == CUSTOM_TOKEN_ISSUER
        except:
            return False
    
    @staticmethod
    def extract_user_info(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract user information from token payload
        
        Args:
            payload: Decoded token payload
            
        Returns:
            User information dictionary
        """
        return {
            'uid': payload.get('user_id'),
            'email': payload.get('email'),
            'name': payload.get('name'),
            'picture': payload.get('picture'),
            'email_verified': payload.get('email_verified', False),
            'is_admin': payload.get('is_admin', False),
            'firebase_provider': payload.get('firebase_provider'),
            'auth_time': payload.get('auth_time'),
            'token_expires_at': payload.get('exp'),
            'token_issued_at': payload.get('iat')
        }

# Singleton instance
custom_token_manager = CustomTokenManager()
