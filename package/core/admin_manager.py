#!/usr/bin/env python3
"""
Admin Manager for managing admin users
Handles admin registration, removal, and permissions management
"""
import datetime
from typing import List, Dict, Any, Optional
from core.firestore_db import firestore_db

class AdminManager:
    def __init__(self):
        """Initialize Admin Manager"""
        self.collection_name = 'admin_users'
        
        # Super admins are always admin (cannot be removed)
        self.SUPER_ADMINS = ['ouday.khaled@gmail.com', 'appsaawt@gmail.com']
    
    def add_admin(self, email: str, role: str = 'admin', added_by: str = '', description: str = '') -> Dict[str, Any]:
        """
        Add a new admin user
        
        Args:
            email: Email address of the new admin
            role: Role of the admin (admin, moderator, etc.)
            added_by: Email of the admin who added this user
            description: Optional description
        
        Returns:
            dict: Result of the operation
        """
        try:
            # Validate email format
            if '@' not in email or '.' not in email:
                return {'success': False, 'error': 'Invalid email format'}
            
            # Check if admin already exists
            existing_admins = self.get_all_admins()
            for admin in existing_admins:
                if admin.get('email') == email:
                    return {'success': False, 'error': f'Admin with email "{email}" already exists'}
            
            admin_data = {
                'email': email,
                'role': role,
                'status': 'active',
                'is_super_admin': email in self.SUPER_ADMINS,
                'description': description,
                'added_by': added_by,
                'created_at': datetime.datetime.now().isoformat(),
                'updated_at': datetime.datetime.now().isoformat(),
                'last_login': None,
                'login_count': 0
            }
            
            # Add to Firestore
            doc_ref = firestore_db.db.collection(self.collection_name).add(admin_data)
            admin_data['id'] = doc_ref[1].id
            
            print(f"✅ Added admin: {email} (Role: {role})")
            return {
                'success': True,
                'admin': admin_data,
                'message': f'Admin "{email}" added successfully'
            }
            
        except Exception as e:
            print(f"❌ Error adding admin: {e}")
            return {'success': False, 'error': str(e)}
    
    def remove_admin(self, admin_id: str, removed_by: str = '') -> Dict[str, Any]:
        """
        Remove an admin user
        
        Args:
            admin_id: ID of the admin to remove
            removed_by: Email of the admin who removed this user
        
        Returns:
            dict: Result of the operation
        """
        try:
            # Get admin info before deleting
            admin_doc = firestore_db.db.collection(self.collection_name).document(admin_id).get()
            if not admin_doc.exists:
                return {'success': False, 'error': 'Admin not found'}
            
            admin_data = admin_doc.to_dict()
            admin_email = admin_data.get('email', 'Unknown')
            
            # Prevent removal of super admins
            if admin_data.get('is_super_admin') or admin_email in self.SUPER_ADMINS:
                return {'success': False, 'error': 'Cannot remove super admin'}
            
            # Archive instead of delete (for audit trail)
            firestore_db.db.collection(self.collection_name).document(admin_id).update({
                'status': 'removed',
                'removed_by': removed_by,
                'removed_at': datetime.datetime.now().isoformat(),
                'updated_at': datetime.datetime.now().isoformat()
            })
            
            print(f"✅ Removed admin: {admin_email} (ID: {admin_id})")
            return {
                'success': True,
                'message': f'Admin "{admin_email}" removed successfully'
            }
            
        except Exception as e:
            print(f"❌ Error removing admin: {e}")
            return {'success': False, 'error': str(e)}
    
    def update_admin(self, admin_id: str, updates: Dict[str, Any], updated_by: str = '') -> Dict[str, Any]:
        """
        Update admin information
        
        Args:
            admin_id: ID of the admin to update
            updates: Dictionary of fields to update
            updated_by: Email of the admin who made the update
        
        Returns:
            dict: Result of the operation
        """
        try:
            # Check if admin exists
            admin_doc = firestore_db.db.collection(self.collection_name).document(admin_id).get()
            if not admin_doc.exists:
                return {'success': False, 'error': 'Admin not found'}
            
            admin_data = admin_doc.to_dict()
            
            # Prevent modification of super admin status
            if 'is_super_admin' in updates and admin_data.get('email') in self.SUPER_ADMINS:
                del updates['is_super_admin']
            
            # Add metadata
            updates['updated_at'] = datetime.datetime.now().isoformat()
            if updated_by:
                updates['updated_by'] = updated_by
            
            # Update in Firestore
            firestore_db.db.collection(self.collection_name).document(admin_id).update(updates)
            
            # Get updated admin data
            updated_doc = firestore_db.db.collection(self.collection_name).document(admin_id).get()
            updated_admin = updated_doc.to_dict()
            updated_admin['id'] = admin_id
            
            print(f"✅ Updated admin: {updated_admin.get('email', 'Unknown')}")
            return {
                'success': True,
                'admin': updated_admin,
                'message': 'Admin updated successfully'
            }
            
        except Exception as e:
            print(f"❌ Error updating admin: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_all_admins(self) -> List[Dict[str, Any]]:
        """
        Get all admin users (including removed ones for audit)
        
        Returns:
            list: List of all admin users
        """
        try:
            admins_ref = firestore_db.db.collection(self.collection_name)
            admins = []
            
            for doc in admins_ref.stream():
                admin_data = doc.to_dict()
                admin_data['id'] = doc.id
                admins.append(admin_data)
            
            # Sort by created_at
            admins.sort(key=lambda x: x.get('created_at', ''), reverse=True)
            return admins
            
        except Exception as e:
            print(f"❌ Error fetching admins: {e}")
            return []
    
    def get_active_admins(self) -> List[Dict[str, Any]]:
        """
        Get only active admin users
        
        Returns:
            list: List of active admin users
        """
        all_admins = self.get_all_admins()
        return [admin for admin in all_admins if admin.get('status') == 'active']
    
    def is_admin(self, email: str) -> bool:
        """
        Check if a user is an admin
        
        Args:
            email: Email address to check
        
        Returns:
            bool: True if user is an admin, False otherwise
        """
        try:
            # Super admins are always admin
            if email in self.SUPER_ADMINS:
                return True
            
            # Check in database
            active_admins = self.get_active_admins()
            for admin in active_admins:
                if admin.get('email') == email:
                    return True
            
            return False
            
        except Exception as e:
            print(f"❌ Error checking admin status: {e}")
            return False
    
    def is_super_admin(self, email: str) -> bool:
        """
        Check if a user is a super admin
        
        Args:
            email: Email address to check
        
        Returns:
            bool: True if user is a super admin, False otherwise
        """
        return email in self.SUPER_ADMINS
    
    def update_login_info(self, email: str) -> Dict[str, Any]:
        """
        Update login information for an admin
        
        Args:
            email: Email of the admin who logged in
        
        Returns:
            dict: Result of the operation
        """
        try:
            active_admins = self.get_active_admins()
            for admin in active_admins:
                if admin.get('email') == email:
                    updates = {
                        'last_login': datetime.datetime.now().isoformat(),
                        'login_count': admin.get('login_count', 0) + 1,
                        'updated_at': datetime.datetime.now().isoformat()
                    }
                    
                    return self.update_admin(admin['id'], updates)
            
            return {'success': False, 'error': 'Admin not found'}
            
        except Exception as e:
            print(f"❌ Error updating login info: {e}")
            return {'success': False, 'error': str(e)}
    
    def ensure_super_admins_exist(self):
        """
        Ensure super admins exist in the database
        Called during startup to initialize super admins
        """
        try:
            existing_admins = self.get_all_admins()
            existing_emails = [admin.get('email') for admin in existing_admins]
            
            for super_admin_email in self.SUPER_ADMINS:
                if super_admin_email not in existing_emails:
                    self.add_admin(
                        email=super_admin_email,
                        role='super_admin',
                        added_by='system',
                        description='System-generated super admin'
                    )
                    print(f"✅ Initialized super admin: {super_admin_email}")
                    
        except Exception as e:
            print(f"❌ Error ensuring super admins exist: {e}")
    
    def get_admin_stats(self) -> Dict[str, Any]:
        """
        Get admin statistics
        
        Returns:
            dict: Admin statistics
        """
        try:
            all_admins = self.get_all_admins()
            active_admins = self.get_active_admins()
            
            return {
                'total_admins': len(all_admins),
                'active_admins': len(active_admins),
                'super_admins': len([admin for admin in active_admins if admin.get('is_super_admin')]),
                'removed_admins': len([admin for admin in all_admins if admin.get('status') == 'removed']),
                'roles': self._get_role_distribution(active_admins),
                'recent_logins': self._get_recent_logins(active_admins),
                'timestamp': datetime.datetime.now().isoformat()
            }
            
        except Exception as e:
            print(f"❌ Error getting admin stats: {e}")
            return {
                'total_admins': 0,
                'active_admins': 0,
                'super_admins': 0,
                'removed_admins': 0,
                'error': str(e),
                'timestamp': datetime.datetime.now().isoformat()
            }
    
    def _get_role_distribution(self, admins: List[Dict[str, Any]]) -> Dict[str, int]:
        """Get distribution of admin roles"""
        roles = {}
        for admin in admins:
            role = admin.get('role', 'unknown')
            roles[role] = roles.get(role, 0) + 1
        return roles
    
    def _get_recent_logins(self, admins: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Get recent login information"""
        recent_logins = []
        for admin in admins:
            if admin.get('last_login'):
                recent_logins.append({
                    'email': admin.get('email'),
                    'last_login': admin.get('last_login'),
                    'login_count': admin.get('login_count', 0)
                })
        
        # Sort by last login time
        recent_logins.sort(key=lambda x: x.get('last_login', ''), reverse=True)
        return recent_logins[:10]  # Return last 10 logins

# Global instance
admin_manager = AdminManager()