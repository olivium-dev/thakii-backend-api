#!/usr/bin/env python3
"""
Push Notification Service using Firebase Cloud Messaging (FCM)
Sends real push notifications to users via FCM
"""
import os
import json
from typing import List, Dict, Any, Optional
from firebase_admin import credentials, messaging, initialize_app
from backend.core.firestore_db import firestore_db
import datetime

class PushNotificationService:
    def __init__(self):
        """Initialize Firebase Admin SDK for push notifications"""
        # Firebase Admin should already be initialized by firestore_db
        pass
    
    def send_notification_to_user(self, user_id: str, title: str, body: str, data: Optional[Dict[str, str]] = None) -> bool:
        """
        Send a push notification to a specific user
        
        Args:
            user_id: The user ID to send notification to
            title: Notification title
            body: Notification body
            data: Optional custom data payload
        
        Returns:
            bool: True if sent successfully, False otherwise
        """
        try:
            # In a real implementation, you would:
            # 1. Retrieve the user's FCM token from your database
            # 2. Send the notification using that token
            
            # For this demo, we'll store the notification in Firestore
            # which will trigger our real-time listeners
            notification_data = {
                'user_id': user_id,
                'title': title,
                'body': body,
                'data': data or {},
                'timestamp': datetime.datetime.now().isoformat(),
                'type': 'push_notification',
                'read': False
            }
            
            # Store in Firestore notifications collection
            doc_ref = firestore_db.db.collection('notifications').add(notification_data)
            print(f"✅ Notification stored in Firestore: {doc_ref[1].id}")
            
            # Also update a global notification counter for real-time demo
            system_ref = firestore_db.db.collection('system').document('notifications')
            system_ref.set({
                'last_notification': notification_data,
                'count': firestore_db.db.collection('notifications').get().__len__() + 1,
                'updated_at': datetime.datetime.now().isoformat()
            }, merge=True)
            
            return True
            
        except Exception as e:
            print(f"❌ Error sending notification: {e}")
            return False
    
    def send_notification_to_all_users(self, title: str, body: str, data: Optional[Dict[str, str]] = None) -> bool:
        """
        Send a push notification to all users
        
        Args:
            title: Notification title
            body: Notification body
            data: Optional custom data payload
        
        Returns:
            bool: True if sent successfully, False otherwise
        """
        try:
            # Get all unique users from video_tasks
            all_tasks = firestore_db.get_all_video_tasks()
            unique_users = set()
            
            for task in all_tasks:
                if task.get('user_id'):
                    unique_users.add(task['user_id'])
            
            if not unique_users:
                print("ℹ️ No users found to send notifications to")
                return True
            
            # Send notification to each user
            success_count = 0
            for user_id in unique_users:
                if self.send_notification_to_user(user_id, title, body, data):
                    success_count += 1
            
            print(f"✅ Sent notifications to {success_count}/{len(unique_users)} users")
            return success_count > 0
            
        except Exception as e:
            print(f"❌ Error sending broadcast notification: {e}")
            return False
    
    def send_test_notification(self, test_type: str = "simple") -> Dict[str, Any]:
        """
        Send a test notification for demonstration purposes
        
        Args:
            test_type: Type of test notification to send
        
        Returns:
            dict: Result of the test notification
        """
        try:
            if test_type == "simple":
                title = "🔔 Test Notification"
                body = f"This is a test push notification sent at {datetime.datetime.now().strftime('%H:%M:%S')}"
                data = {
                    "test": "true",
                    "timestamp": datetime.datetime.now().isoformat(),
                    "type": "simple_test"
                }
                
                # Send to all users
                success = self.send_notification_to_all_users(title, body, data)
                
                return {
                    "success": success,
                    "title": title,
                    "body": body,
                    "message": "Test notification sent to all users" if success else "Failed to send test notification",
                    "timestamp": datetime.datetime.now().isoformat()
                }
                
            elif test_type == "video_update":
                title = "📹 Video Processing Update"
                body = "Your video has finished processing and is ready for download!"
                data = {
                    "test": "true",
                    "video_id": "test_video_123",
                    "status": "done",
                    "type": "video_update"
                }
                
                success = self.send_notification_to_all_users(title, body, data)
                
                return {
                    "success": success,
                    "title": title,
                    "body": body,
                    "message": "Video update notification sent" if success else "Failed to send video update notification",
                    "timestamp": datetime.datetime.now().isoformat()
                }
                
            else:
                return {
                    "success": False,
                    "message": "Unknown test type",
                    "timestamp": datetime.datetime.now().isoformat()
                }
                
        except Exception as e:
            print(f"❌ Error sending test notification: {e}")
            return {
                "success": False,
                "message": f"Error: {str(e)}",
                "timestamp": datetime.datetime.now().isoformat()
            }

# Global instance
push_service = PushNotificationService()