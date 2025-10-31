#!/usr/bin/env python3
"""
Test script to verify worker connectivity FROM the backend server
This will be uploaded and run on thakii-02 to diagnose the issue
"""

import requests
import time
import sys

def test_worker_health(worker_url, worker_name):
    """Test if backend can reach worker health endpoint"""
    print(f"\n🔍 Testing {worker_name} Worker: {worker_url}")
    print("="*60)
    
    try:
        health_url = f"{worker_url.rstrip('/')}/health"
        print(f"Request URL: {health_url}")
        print(f"Timeout: 10s")
        
        start_time = time.time()
        response = requests.get(health_url, timeout=10)
        elapsed = time.time() - start_time
        
        print(f"✅ Response received in {elapsed:.2f}s")
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.json()}")
        
        if response.status_code == 200:
            print(f"✅ {worker_name} worker is HEALTHY and REACHABLE")
            return True
        else:
            print(f"⚠️ {worker_name} worker returned non-200 status: {response.status_code}")
            return False
            
    except requests.exceptions.Timeout:
        print(f"❌ {worker_name} worker TIMEOUT (>10s)")
        return False
    except requests.exceptions.ConnectionError as e:
        print(f"❌ {worker_name} worker CONNECTION ERROR: {e}")
        return False
    except Exception as e:
        print(f"❌ {worker_name} worker ERROR: {e}")
        return False

def test_worker_trigger(worker_url, worker_name):
    """Test if backend can trigger worker processing"""
    print(f"\n🚀 Testing {worker_name} Worker Trigger: {worker_url}")
    print("="*60)
    
    payload = {
        "video_id": "test-connectivity-check",
        "user_id": "test-user",
        "filename": "test.txt",
        "s3_key": "test/test.txt"
    }
    
    try:
        trigger_url = f"{worker_url.rstrip('/')}/process-from-s3"
        print(f"Request URL: {trigger_url}")
        print(f"Payload: {payload}")
        print(f"Timeout: 30s")
        
        start_time = time.time()
        response = requests.post(
            trigger_url,
            json=payload,
            timeout=30,
            headers={'Content-Type': 'application/json'}
        )
        elapsed = time.time() - start_time
        
        print(f"✅ Response received in {elapsed:.2f}s")
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
        
        if response.status_code == 201:
            print(f"✅ {worker_name} worker TRIGGER SUCCESSFUL")
            return True
        else:
            print(f"⚠️ {worker_name} worker trigger returned status: {response.status_code}")
            return False
            
    except requests.exceptions.Timeout:
        print(f"❌ {worker_name} worker trigger TIMEOUT (>30s)")
        return False
    except requests.exceptions.ConnectionError as e:
        print(f"❌ {worker_name} worker trigger CONNECTION ERROR: {e}")
        return False
    except Exception as e:
        print(f"❌ {worker_name} worker trigger ERROR: {e}")
        return False

def main():
    print("🧪 BACKEND SERVER - WORKER CONNECTIVITY TEST")
    print("="*60)
    print(f"Running from: Backend Server (thakii-02)")
    print(f"Testing worker connectivity from backend's perspective")
    print()
    
    # Test Primary Worker
    primary_url = "https://thakii-3.fanusdigital.site/thakii-worker"
    primary_health = test_worker_health(primary_url, "Primary (thakii-3)")
    primary_trigger = test_worker_trigger(primary_url, "Primary (thakii-3)") if primary_health else False
    
    # Test Fallback Worker
    fallback_url = "https://thakii-02.fanusdigital.site/thakii-worker"
    fallback_health = test_worker_health(fallback_url, "Fallback (thakii-02)")
    fallback_trigger = test_worker_trigger(fallback_url, "Fallback (thakii-02)") if fallback_health else False
    
    # Summary
    print("\n" + "="*60)
    print("📊 CONNECTIVITY TEST SUMMARY")
    print("="*60)
    print(f"Primary Worker Health:   {'✅ PASS' if primary_health else '❌ FAIL'}")
    print(f"Primary Worker Trigger:  {'✅ PASS' if primary_trigger else '❌ FAIL'}")
    print(f"Fallback Worker Health:  {'✅ PASS' if fallback_health else '❌ FAIL'}")
    print(f"Fallback Worker Trigger: {'✅ PASS' if fallback_trigger else '❌ FAIL'}")
    
    if primary_health and primary_trigger:
        print("\n✅ PRIMARY WORKER: Fully operational from backend")
    elif fallback_health and fallback_trigger:
        print("\n✅ FALLBACK WORKER: Fully operational from backend")
    else:
        print("\n❌ CRITICAL: Backend cannot reach ANY workers!")
        print("This explains why automatic triggering fails.")
    
    # Exit code
    if (primary_health and primary_trigger) or (fallback_health and fallback_trigger):
        return 0
    else:
        return 1

if __name__ == "__main__":
    sys.exit(main())

