#!/usr/bin/env python3
"""
Worker Manager for Primary/Fallback Worker Selection
Handles intelligent worker routing with automatic failover
"""

import os
import requests
import datetime
from typing import Optional, Dict, Any, Tuple
from dotenv import load_dotenv

load_dotenv()


class WorkerManager:
    def __init__(self):
        """Initialize Worker Manager with primary and fallback workers"""
        # Load worker URLs from environment
        self.primary_worker_url = os.getenv('PRIMARY_WORKER_URL', '').strip()
        self.fallback_worker_url = os.getenv('FALLBACK_WORKER_URL', '').strip()
        
        # Legacy support - if new variables not set, use old WORKER_SERVICE_URL
        legacy_url = os.getenv('WORKER_SERVICE_URL', '').strip()
        
        if not self.primary_worker_url and legacy_url:
            self.primary_worker_url = legacy_url
            print(f"⚠️ Using legacy WORKER_SERVICE_URL as primary: {legacy_url}")
        
        # Worker priority mode: primary-only, primary-with-fallback, round-robin
        self.priority_mode = os.getenv('WORKER_PRIORITY_MODE', 'primary-with-fallback').lower()
        
        # Health check timeout (seconds)
        self.health_check_timeout = int(os.getenv('WORKER_HEALTH_TIMEOUT', '5'))
        
        # Request timeout for worker processing (seconds)
        self.request_timeout = int(os.getenv('WORKER_REQUEST_TIMEOUT', '30'))
        
        print(f"🔧 Worker Manager initialized:")
        print(f"   Primary Worker: {self.primary_worker_url or 'NOT SET'}")
        print(f"   Fallback Worker: {self.fallback_worker_url or 'NOT SET'}")
        print(f"   Priority Mode: {self.priority_mode}")
        print(f"   Health Check Timeout: {self.health_check_timeout}s")
    
    def check_worker_health(self, worker_url: str, timeout: Optional[int] = None) -> Dict[str, Any]:
        """
        Check health of a specific worker
        
        Args:
            worker_url: URL of the worker to check
            timeout: Custom timeout for health check (default: uses configured timeout)
        
        Returns:
            dict: Health status information with keys:
                - healthy (bool): Whether worker is healthy
                - response_time (float): Response time in seconds
                - status_code (int): HTTP status code
                - error (str): Error message if unhealthy
                - checked_at (str): ISO timestamp of check
        """
        if not worker_url:
            return {
                'healthy': False,
                'response_time': None,
                'status_code': None,
                'error': 'Worker URL not configured',
                'checked_at': datetime.datetime.now().isoformat()
            }
        
        timeout = timeout or self.health_check_timeout
        
        try:
            health_url = f"{worker_url.rstrip('/')}/health"
            response = requests.get(health_url, timeout=timeout)
            
            if response.status_code == 200:
                return {
                    'healthy': True,
                    'response_time': response.elapsed.total_seconds(),
                    'status_code': response.status_code,
                    'worker_info': response.json() if response.content else {},
                    'error': None,
                    'checked_at': datetime.datetime.now().isoformat()
                }
            else:
                return {
                    'healthy': False,
                    'response_time': response.elapsed.total_seconds(),
                    'status_code': response.status_code,
                    'worker_info': None,
                    'error': f'HTTP {response.status_code}',
                    'checked_at': datetime.datetime.now().isoformat()
                }
                
        except requests.exceptions.Timeout:
            return {
                'healthy': False,
                'response_time': None,
                'status_code': None,
                'worker_info': None,
                'error': 'Connection timeout',
                'checked_at': datetime.datetime.now().isoformat()
            }
        except requests.exceptions.ConnectionError:
            return {
                'healthy': False,
                'response_time': None,
                'status_code': None,
                'worker_info': None,
                'error': 'Connection refused',
                'checked_at': datetime.datetime.now().isoformat()
            }
        except Exception as e:
            return {
                'healthy': False,
                'response_time': None,
                'status_code': None,
                'worker_info': None,
                'error': str(e),
                'checked_at': datetime.datetime.now().isoformat()
            }
    
    def select_available_worker(self, check_health: bool = True) -> Tuple[Optional[str], str]:
        """
        Select an available worker based on health and priority mode
        
        Args:
            check_health: Whether to perform health check before selection
        
        Returns:
            tuple: (worker_url, worker_name) or (None, 'none') if no workers available
                worker_name will be 'primary', 'fallback', or 'none'
        """
        # Mode: primary-only - only use primary worker
        if self.priority_mode == 'primary-only':
            if self.primary_worker_url:
                if not check_health:
                    return (self.primary_worker_url, 'primary')
                
                health = self.check_worker_health(self.primary_worker_url)
                if health['healthy']:
                    return (self.primary_worker_url, 'primary')
            
            return (None, 'none')
        
        # Mode: primary-with-fallback (default)
        if self.priority_mode == 'primary-with-fallback':
            # Try primary first
            if self.primary_worker_url:
                if not check_health:
                    return (self.primary_worker_url, 'primary')
                
                primary_health = self.check_worker_health(self.primary_worker_url)
                if primary_health['healthy']:
                    print(f"✅ Primary worker healthy (response: {primary_health['response_time']:.2f}s)")
                    return (self.primary_worker_url, 'primary')
                else:
                    print(f"⚠️ Primary worker unhealthy: {primary_health['error']}")
            
            # Fallback to secondary
            if self.fallback_worker_url:
                if not check_health:
                    print(f"🔄 Using fallback worker (health check disabled)")
                    return (self.fallback_worker_url, 'fallback')
                
                fallback_health = self.check_worker_health(self.fallback_worker_url)
                if fallback_health['healthy']:
                    print(f"✅ Fallback worker healthy (response: {fallback_health['response_time']:.2f}s)")
                    return (self.fallback_worker_url, 'fallback')
                else:
                    print(f"❌ Fallback worker also unhealthy: {fallback_health['error']}")
            
            return (None, 'none')
        
        # Mode: round-robin - alternate between workers (future enhancement)
        # For now, treat as primary-with-fallback
        # FIXED: Avoid infinite recursion by explicitly handling this case
        if self.priority_mode == 'round-robin':
            # Temporarily use primary-with-fallback logic for round-robin
            # Try primary first
            if self.primary_worker_url:
                if not check_health:
                    return (self.primary_worker_url, 'primary')
                
                primary_health = self.check_worker_health(self.primary_worker_url)
                if primary_health['healthy']:
                    return (self.primary_worker_url, 'primary')
            
            # Fallback to secondary
            if self.fallback_worker_url:
                if not check_health:
                    return (self.fallback_worker_url, 'fallback')
                
                fallback_health = self.check_worker_health(self.fallback_worker_url)
                if fallback_health['healthy']:
                    return (self.fallback_worker_url, 'fallback')
            
            return (None, 'none')
        
        # Unknown mode - default to primary-only
        if self.primary_worker_url:
            if not check_health:
                return (self.primary_worker_url, 'primary')
            
            health = self.check_worker_health(self.primary_worker_url)
            if health['healthy']:
                return (self.primary_worker_url, 'primary')
        
        return (None, 'none')
    
    def get_all_workers_health(self) -> Dict[str, Any]:
        """
        Get health status of all configured workers
        
        Returns:
            dict: Health information for all workers
        """
        result = {
            'timestamp': datetime.datetime.now().isoformat(),
            'priority_mode': self.priority_mode,
            'workers': {}
        }
        
        if self.primary_worker_url:
            result['workers']['primary'] = {
                'url': self.primary_worker_url,
                'health': self.check_worker_health(self.primary_worker_url)
            }
        
        if self.fallback_worker_url:
            result['workers']['fallback'] = {
                'url': self.fallback_worker_url,
                'health': self.check_worker_health(self.fallback_worker_url)
            }
        
        # Summary
        healthy_count = sum(1 for w in result['workers'].values() if w['health']['healthy'])
        result['summary'] = {
            'total_workers': len(result['workers']),
            'healthy_workers': healthy_count,
            'unhealthy_workers': len(result['workers']) - healthy_count
        }
        
        return result
    
    def trigger_worker(self, worker_url: str, payload: Dict[str, Any]) -> Tuple[bool, int, str]:
        """
        Trigger a specific worker with a processing request
        
        Args:
            worker_url: URL of the worker to trigger
            payload: Request payload (video_id, user_id, filename, s3_key)
        
        Returns:
            tuple: (success, status_code, response_text)
        """
        try:
            response = requests.post(
                f"{worker_url.rstrip('/')}/process-from-s3",
                json=payload,
                timeout=self.request_timeout,
                headers={'Content-Type': 'application/json'}
            )
            
            success = response.status_code == 201
            return (success, response.status_code, response.text)
            
        except requests.exceptions.Timeout:
            return (False, 0, 'Request timeout')
        except requests.exceptions.ConnectionError:
            return (False, 0, 'Connection refused')
        except Exception as e:
            return (False, 0, str(e))
    
    def trigger_with_fallback(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Trigger worker processing with automatic fallback
        
        Args:
            payload: Request payload (video_id, user_id, filename, s3_key)
        
        Returns:
            dict: Result with keys:
                - success (bool): Whether processing was triggered
                - worker_used (str): 'primary', 'fallback', or 'none'
                - status_code (int): HTTP status code
                - response_text (str): Response message
                - error (str): Error message if failed
        """
        video_id = payload.get('video_id', 'unknown')
        
        print(f"🚀 Triggering worker for video {video_id}")
        print(f"   Payload: {payload}")
        
        # Select available worker
        worker_url, worker_name = self.select_available_worker(check_health=True)
        
        if not worker_url:
            print(f"❌ No workers available for video {video_id}")
            return {
                'success': False,
                'worker_used': 'none',
                'status_code': 0,
                'response_text': '',
                'error': 'No workers available'
            }
        
        print(f"📍 Selected {worker_name} worker: {worker_url}")
        
        # Try selected worker
        success, status_code, response_text = self.trigger_worker(worker_url, payload)
        
        if success:
            print(f"✅ {worker_name.capitalize()} worker triggered successfully: {video_id}")
            return {
                'success': True,
                'worker_used': worker_name,
                'worker_url': worker_url,
                'status_code': status_code,
                'response_text': response_text,
                'error': None
            }
        
        # If primary failed and fallback is available, try fallback
        if worker_name == 'primary' and self.fallback_worker_url and self.priority_mode == 'primary-with-fallback':
            print(f"⚠️ Primary worker failed (status: {status_code}), trying fallback...")
            
            # Try fallback without health check (already failed primary, need to try)
            fallback_success, fallback_status, fallback_response = self.trigger_worker(
                self.fallback_worker_url, payload
            )
            
            if fallback_success:
                print(f"✅ Fallback worker succeeded for video {video_id}")
                return {
                    'success': True,
                    'worker_used': 'fallback',
                    'worker_url': self.fallback_worker_url,
                    'status_code': fallback_status,
                    'response_text': fallback_response,
                    'error': None,
                    'note': f'Primary failed (HTTP {status_code}), used fallback'
                }
            else:
                print(f"❌ Both workers failed for video {video_id}")
                return {
                    'success': False,
                    'worker_used': 'fallback',
                    'worker_url': self.fallback_worker_url,
                    'status_code': fallback_status,
                    'response_text': fallback_response,
                    'error': f'Both workers failed - Primary: HTTP {status_code}, Fallback: HTTP {fallback_status}'
                }
        
        # Single worker failed or no fallback available
        print(f"❌ Worker trigger failed: {video_id} - HTTP {status_code}")
        return {
            'success': False,
            'worker_used': worker_name,
            'worker_url': worker_url,
            'status_code': status_code,
            'response_text': response_text,
            'error': f'Worker trigger failed: HTTP {status_code}'
        }


# Global instance
worker_manager = WorkerManager()

