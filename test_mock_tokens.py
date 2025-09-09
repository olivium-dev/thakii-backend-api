#!/usr/bin/env python3
"""
Mock Token Testing Script
Generates mock tokens and tests all backend APIs
"""

import requests
import json
import sys
import os
from datetime import datetime

# Backend URL
BASE_URL = "https://thakii-02.fanusdigital.site"

def test_mock_tokens():
    """Test the mock token system"""
    print("🧪 TESTING MOCK TOKEN SYSTEM")
    print("=" * 50)
    
    # Test 1: Generate mock admin token
    print("\n1. 🔑 Generating Mock Admin Token...")
    try:
        response = requests.post(f"{BASE_URL}/auth/mock-admin-token")
        if response.status_code == 200:
            data = response.json()
            admin_token = data['custom_token']
            print("✅ Mock Admin Token Generated!")
            print(f"   User: {data['user']['name']} ({data['user']['email']})")
            print(f"   Admin: {data['user']['is_admin']}")
            print(f"   Token: {admin_token[:50]}...")
        else:
            print(f"❌ Failed to generate admin token: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error generating admin token: {e}")
        return False
    
    # Test 2: Generate mock user token
    print("\n2. 🔑 Generating Mock User Token...")
    try:
        response = requests.post(f"{BASE_URL}/auth/mock-user-token")
        if response.status_code == 200:
            data = response.json()
            user_token = data['custom_token']
            print("✅ Mock User Token Generated!")
            print(f"   User: {data['user']['name']} ({data['user']['email']})")
            print(f"   Admin: {data['user']['is_admin']}")
            print(f"   Token: {user_token[:50]}...")
        else:
            print(f"❌ Failed to generate user token: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error generating user token: {e}")
        return False
    
    # Test 3: Test APIs with admin token
    print("\n3. 🔧 Testing APIs with Admin Token...")
    headers = {"Authorization": f"Bearer {admin_token}"}
    
    # Test /auth/user
    try:
        response = requests.get(f"{BASE_URL}/auth/user", headers=headers)
        if response.status_code == 200:
            user_info = response.json()
            print(f"✅ /auth/user: {user_info['user']['name']} (Admin: {user_info['user']['is_admin']})")
        else:
            print(f"❌ /auth/user failed: {response.text}")
    except Exception as e:
        print(f"❌ /auth/user error: {e}")
    
    # Test /list
    try:
        response = requests.get(f"{BASE_URL}/list", headers=headers)
        if response.status_code == 200:
            videos = response.json()
            print(f"✅ /list: {len(videos)} videos found")
        else:
            print(f"❌ /list failed: {response.text}")
    except Exception as e:
        print(f"❌ /list error: {e}")
    
    # Test /admin/videos
    try:
        response = requests.get(f"{BASE_URL}/admin/videos", headers=headers)
        if response.status_code == 200:
            videos = response.json()
            print(f"✅ /admin/videos: {len(videos)} videos found")
        else:
            print(f"❌ /admin/videos failed: {response.text}")
    except Exception as e:
        print(f"❌ /admin/videos error: {e}")
    
    # Test /admin/stats
    try:
        response = requests.get(f"{BASE_URL}/admin/stats", headers=headers)
        if response.status_code == 200:
            stats = response.json()
            print(f"✅ /admin/stats: {stats}")
        else:
            print(f"❌ /admin/stats failed: {response.text}")
    except Exception as e:
        print(f"❌ /admin/stats error: {e}")
    
    # Test 4: Test APIs with regular user token
    print("\n4. 👤 Testing APIs with User Token...")
    headers = {"Authorization": f"Bearer {user_token}"}
    
    # Test /auth/user
    try:
        response = requests.get(f"{BASE_URL}/auth/user", headers=headers)
        if response.status_code == 200:
            user_info = response.json()
            print(f"✅ /auth/user: {user_info['user']['name']} (Admin: {user_info['user']['is_admin']})")
        else:
            print(f"❌ /auth/user failed: {response.text}")
    except Exception as e:
        print(f"❌ /auth/user error: {e}")
    
    # Test /list
    try:
        response = requests.get(f"{BASE_URL}/list", headers=headers)
        if response.status_code == 200:
            videos = response.json()
            print(f"✅ /list: {len(videos)} videos found")
        else:
            print(f"❌ /list failed: {response.text}")
    except Exception as e:
        print(f"❌ /list error: {e}")
    
    # Test /admin/videos (should fail for regular user)
    try:
        response = requests.get(f"{BASE_URL}/admin/videos", headers=headers)
        if response.status_code == 403:
            print(f"✅ /admin/videos: Correctly denied for regular user")
        else:
            print(f"⚠️ /admin/videos: Unexpected response {response.status_code}: {response.text}")
    except Exception as e:
        print(f"❌ /admin/videos error: {e}")
    
    print("\n🎉 MOCK TOKEN TESTING COMPLETE!")
    print("\n📋 TOKENS FOR MANUAL TESTING:")
    print(f"Admin Token: {admin_token}")
    print(f"User Token: {user_token}")
    
    return True

if __name__ == "__main__":
    # Check if mock endpoints exist first
    print("🔍 Checking if mock token endpoints exist...")
    try:
        response = requests.post(f"{BASE_URL}/auth/mock-admin-token")
        if response.status_code == 404:
            print("❌ Mock token endpoints not found. Deploy the backend first.")
            sys.exit(1)
    except Exception as e:
        print(f"❌ Cannot reach backend: {e}")
        sys.exit(1)
    
    test_mock_tokens()
