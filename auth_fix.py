#!/usr/bin/env python3
"""
Fix Firebase Token Verification in Backend
Creates a new login endpoint that properly handles Firebase tokens
"""

import requests
import json

def test_firebase_token_verification():
    """Test the current Firebase token verification issue"""
    
    # Your actual Firebase token from the logs
    firebase_token = "eyJhbGciOiJSUzI1NiIsImtpZCI6ImUzZWU3ZTAyOGUzODg1YTM0NWNlMDcwNTVmODQ2ODYyMjU1YTcwNDYiLCJ0eXAiOiJKV1QifQ.eyJuYW1lIjoiT3VkYXkgS2hhbGVkIiwicGljdHVyZSI6Imh0dHBzOi8vbGgzLmdvb2dsZXVzZXJjb250ZW50LmNvbS9hL0FDZzhvY0pZYjVOMlJ2Q285WkJWWnV3OWlLUmVkYmVKYlJfUTMxbWlBX0Z3WWNpY1BmN3p3blk9czk2LWMiLCJpc3MiOiJodHRwczovL3NlY3VyZXRva2VuLmdvb2dsZS5jb20vdGhha2lpLTk3M2UzIiwiYXVkIjoidGhha2lpLTk3M2UzIiwiYXV0aF90aW1lIjoxNzU3Njc0MDE4LCJ1c2VyX2lkIjoiV1cwTU13R2dxYlpzYXV5dDBuRnpaQjFSa2JkMiIsInN1YiI6IldXME1Nd0dncWJac2F1eXQwbkZ6WkIxUmtiZDIiLCJpYXQiOjE3NTc2NzQwMTgsImV4cCI6MTc1NzY3NzYxOCwiZW1haWwiOiJvdWRheS5raGFsZWRAZ21haWwuY29tIiwiZW1haWxfdmVyaWZpZWQiOnRydWUsImZpcmViYXNlIjp7ImlkZW50aXRpZXMiOnsiZ29vZ2xlLmNvbSI6WyIxMDA4NDI4NTgyNTQ2MTUwNjkwNTMiXSwiZW1haWwiOlsib3VkYXkua2hhbGVkQGdtYWlsLmNvbSJdfSwic2lnbl9pbl9wcm92aWRlciI6Imdvb2dsZS5jb20ifX0.A44AkJJVlpTl_e3oROunMo-6P68FP2lCjoxVp91f2_bSvUzx37XdGHi971ZF_yjiQpFqohaiD_BZ_6HmVhGEPJPqW4P6Vj6eWwX7GVifp-W658-d1aAyL1YTaZ8CpCSBckfuAWf89JzmyYkOBtAo8FotD3YZOh1VvdIvj3lzHVMzcxclok4Uu0D-1gV_pW4bGvT8gQRtnnFGdoOcDZVctnH-y_fzfxakghId9NhgsfNw8AIPH1gxoStIZP0scooUCtyAFjC2wYGm2C0fEPo_tZJJEoG9FuJdUK6RvntJgrPDwwQ8P44DbR-NNpVxhJRJBXOicVFi1vG3Bw9OAWbcGw"
    
    backend_url = "https://thakii-02.fanusdigital.site/thakii-be"
    
    print("🔍 === TESTING FIREBASE TOKEN VERIFICATION ===")
    print()
    
    # Test 1: Exchange token endpoint
    print("1️⃣ Testing token exchange:")
    try:
        response = requests.post(
            f"{backend_url}/auth/exchange-token",
            headers={'Authorization': f'Bearer {firebase_token}'},
            timeout=10
        )
        print(f"   Status: {response.status_code}")
        print(f"   Response: {response.text}")
    except Exception as e:
        print(f"   Error: {e}")
    
    print()
    
    # Test 2: Direct list call
    print("2️⃣ Testing direct list call:")
    try:
        response = requests.get(
            f"{backend_url}/list",
            headers={'Authorization': f'Bearer {firebase_token}'},
            timeout=10
        )
        print(f"   Status: {response.status_code}")
        print(f"   Response: {response.text[:200]}...")
    except Exception as e:
        print(f"   Error: {e}")
    
    print()
    
    # Test 3: Decode the Firebase token to see what's in it
    print("3️⃣ Analyzing Firebase token content:")
    import jwt
    try:
        # Decode without verification to see the payload
        decoded = jwt.decode(firebase_token, options={"verify_signature": False})
        print(f"   User ID: {decoded.get('user_id', 'N/A')}")
        print(f"   Email: {decoded.get('email', 'N/A')}")
        print(f"   Issuer: {decoded.get('iss', 'N/A')}")
        print(f"   Audience: {decoded.get('aud', 'N/A')}")
        print(f"   Expires: {decoded.get('exp', 'N/A')}")
    except Exception as e:
        print(f"   Decode error: {e}")

if __name__ == "__main__":
    test_firebase_token_verification()
