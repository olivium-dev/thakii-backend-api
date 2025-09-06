#!/usr/bin/env python3
"""
Server Manager for managing multiple backend processing servers
Handles server registration, health checks, and workload distribution
"""
import datetime
from typing import List, Dict, Any, Optional
from backend.core.firestore_db import firestore_db
import requests
import time

class ServerManager:
    def __init__(self):
        """Initialize Server Manager"""
        self.collection_name = 'processing_servers'
    
    def add_server(self, server_name: str, server_url: str, server_type: str = 'processing', description: str = '') -> Dict[str, Any]:
        """
        Add a new processing server to the pool
        
        Args:
            server_name: Unique name for the server
            server_url: Full URL of the server (e.g., http://server1.example.com:5001)
            server_type: Type of server (processing, backup, etc.)
            description: Optional description of the server
        
        Returns:
            dict: Result of the operation
        """
        try:
            # Validate URL format
            if not server_url.startswith(('http://', 'https://')):
                return {'success': False, 'error': 'Server URL must start with http:// or https://'}
            
            # Check if server name already exists
            existing_servers = self.get_all_servers()
            for server in existing_servers:
                if server.get('name') == server_name:
                    return {'success': False, 'error': f'Server with name "{server_name}" already exists'}
            
            # Test server connectivity
            health_status = self._check_server_health(server_url)
            
            server_data = {
                'name': server_name,
                'url': server_url,
                'type': server_type,
                'description': description,
                'status': 'active' if health_status['healthy'] else 'inactive',
                'health_status': health_status,
                'created_at': datetime.datetime.now().isoformat(),
                'updated_at': datetime.datetime.now().isoformat(),
                'total_jobs_processed': 0,
                'current_load': 0,
                'last_health_check': datetime.datetime.now().isoformat()
            }
            
            # Add to Firestore
            doc_ref = firestore_db.db.collection(self.collection_name).add(server_data)
            server_data['id'] = doc_ref[1].id
            
            print(f"✅ Added server: {server_name} ({server_url})")
            return {
                'success': True,
                'server': server_data,
                'message': f'Server "{server_name}" added successfully'
            }
            
        except Exception as e:
            print(f"❌ Error adding server: {e}")
            return {'success': False, 'error': str(e)}
    
    def remove_server(self, server_id: str) -> Dict[str, Any]:
        """
        Remove a server from the pool
        
        Args:
            server_id: ID of the server to remove
        
        Returns:
            dict: Result of the operation
        """
        try:
            # Get server info before deleting
            server_doc = firestore_db.db.collection(self.collection_name).document(server_id).get()
            if not server_doc.exists:
                return {'success': False, 'error': 'Server not found'}
            
            server_data = server_doc.to_dict()
            server_name = server_data.get('name', 'Unknown')
            
            # Delete from Firestore
            firestore_db.db.collection(self.collection_name).document(server_id).delete()
            
            print(f"✅ Removed server: {server_name} (ID: {server_id})")
            return {
                'success': True,
                'message': f'Server "{server_name}" removed successfully'
            }
            
        except Exception as e:
            print(f"❌ Error removing server: {e}")
            return {'success': False, 'error': str(e)}
    
    def update_server(self, server_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update server information
        
        Args:
            server_id: ID of the server to update
            updates: Dictionary of fields to update
        
        Returns:
            dict: Result of the operation
        """
        try:
            # Check if server exists
            server_doc = firestore_db.db.collection(self.collection_name).document(server_id).get()
            if not server_doc.exists:
                return {'success': False, 'error': 'Server not found'}
            
            # Add updated timestamp
            updates['updated_at'] = datetime.datetime.now().isoformat()
            
            # Update in Firestore
            firestore_db.db.collection(self.collection_name).document(server_id).update(updates)
            
            # Get updated server data
            updated_doc = firestore_db.db.collection(self.collection_name).document(server_id).get()
            updated_server = updated_doc.to_dict()
            updated_server['id'] = server_id
            
            print(f"✅ Updated server: {updated_server.get('name', 'Unknown')}")
            return {
                'success': True,
                'server': updated_server,
                'message': 'Server updated successfully'
            }
            
        except Exception as e:
            print(f"❌ Error updating server: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_all_servers(self) -> List[Dict[str, Any]]:
        """
        Get all registered servers
        
        Returns:
            list: List of all servers
        """
        try:
            servers_ref = firestore_db.db.collection(self.collection_name)
            servers = []
            
            for doc in servers_ref.stream():
                server_data = doc.to_dict()
                server_data['id'] = doc.id
                servers.append(server_data)
            
            # Sort by created_at
            servers.sort(key=lambda x: x.get('created_at', ''), reverse=True)
            return servers
            
        except Exception as e:
            print(f"❌ Error fetching servers: {e}")
            return []
    
    def get_active_servers(self) -> List[Dict[str, Any]]:
        """
        Get only active/healthy servers for workload distribution
        
        Returns:
            list: List of active servers
        """
        all_servers = self.get_all_servers()
        return [server for server in all_servers if server.get('status') == 'active']
    
    def check_all_servers_health(self) -> Dict[str, Any]:
        """
        Check health of all registered servers and update their status
        
        Returns:
            dict: Summary of health check results
        """
        try:
            servers = self.get_all_servers()
            healthy_count = 0
            unhealthy_count = 0
            
            for server in servers:
                health_status = self._check_server_health(server['url'])
                new_status = 'active' if health_status['healthy'] else 'inactive'
                
                # Update server status in database
                self.update_server(server['id'], {
                    'status': new_status,
                    'health_status': health_status,
                    'last_health_check': datetime.datetime.now().isoformat()
                })
                
                if health_status['healthy']:
                    healthy_count += 1
                else:
                    unhealthy_count += 1
            
            return {
                'total_servers': len(servers),
                'healthy_servers': healthy_count,
                'unhealthy_servers': unhealthy_count,
                'timestamp': datetime.datetime.now().isoformat()
            }
            
        except Exception as e:
            print(f"❌ Error checking servers health: {e}")
            return {
                'total_servers': 0,
                'healthy_servers': 0,
                'unhealthy_servers': 0,
                'error': str(e),
                'timestamp': datetime.datetime.now().isoformat()
            }
    
    def get_best_server_for_job(self) -> Optional[Dict[str, Any]]:
        """
        Get the best available server for processing a new job
        Uses load balancing based on current load
        
        Returns:
            dict: Best server for the job, or None if no servers available
        """
        active_servers = self.get_active_servers()
        
        if not active_servers:
            return None
        
        # Sort by current load (ascending) to get least loaded server
        active_servers.sort(key=lambda x: x.get('current_load', 0))
        
        return active_servers[0]
    
    def _check_server_health(self, server_url: str) -> Dict[str, Any]:
        """
        Check health of a specific server
        
        Args:
            server_url: URL of the server to check
        
        Returns:
            dict: Health status information
        """
        try:
            # Try to connect to the server's health endpoint
            health_url = f"{server_url.rstrip('/')}/health"
            response = requests.get(health_url, timeout=5)
            
            if response.status_code == 200:
                health_data = response.json()
                return {
                    'healthy': True,
                    'response_time': response.elapsed.total_seconds(),
                    'status_code': response.status_code,
                    'server_info': health_data,
                    'error': None,
                    'checked_at': datetime.datetime.now().isoformat()
                }
            else:
                return {
                    'healthy': False,
                    'response_time': response.elapsed.total_seconds(),
                    'status_code': response.status_code,
                    'server_info': None,
                    'error': f'HTTP {response.status_code}',
                    'checked_at': datetime.datetime.now().isoformat()
                }
                
        except requests.exceptions.Timeout:
            return {
                'healthy': False,
                'response_time': None,
                'status_code': None,
                'server_info': None,
                'error': 'Connection timeout',
                'checked_at': datetime.datetime.now().isoformat()
            }
        except requests.exceptions.ConnectionError:
            return {
                'healthy': False,
                'response_time': None,
                'status_code': None,
                'server_info': None,
                'error': 'Connection refused',
                'checked_at': datetime.datetime.now().isoformat()
            }
        except Exception as e:
            return {
                'healthy': False,
                'response_time': None,
                'status_code': None,
                'server_info': None,
                'error': str(e),
                'checked_at': datetime.datetime.now().isoformat()
            }

# Global instance
server_manager = ServerManager()