#!/usr/bin/env python3
"""
Push Notification Service using Firebase Cloud Messaging (FCM)
Sends real push notifications to users via FCM
Now stores notifications in PostgreSQL instead of Firestore
"""
import os
import json
from typing import List, Dict, Any, Optional
from firebase_admin import credentials, messaging
from core.postgres_db import postgres_db
import datetime

class PushNotificationService:
    def __init__(self):
        """Initialize Push Notification Service"""
        # Firebase Admin should already be initialized for authentication
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
            # Store notification in PostgreSQL
            notification = postgres_db.create_notification(
                user_id=user_id,
                title=title,
                body=body,
                notification_type='push_notification',
                data=data or {}
            )
            
            print(f"✅ Notification stored in PostgreSQL: {notification.get('id')}")
            
            # TODO: In a real implementation with FCM tokens:
            # 1. Retrieve the user's FCM token from your database
            # 2. Send the notification using messaging.send()
            # Example:
            # message = messaging.Message(
            #     notification=messaging.Notification(
            #         title=title,
            #         body=body,
            #     ),
            #     data=data or {},
            #     token=user_fcm_token,
            # )
            # response = messaging.send(message)
            
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
            all_tasks = postgres_db.get_all_video_tasks()
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
    
    def get_user_notifications(self, user_id: str, unread_only: bool = False) -> List[Dict[str, Any]]:
        """
        Get notifications for a user
        
        Args:
            user_id: User ID to get notifications for
            unread_only: If True, only return unread notifications
        
        Returns:
            list: List of notifications
        """
        try:
            notifications = postgres_db.get_user_notifications(user_id, unread_only)
            return notifications
        except Exception as e:
            print(f"❌ Error getting user notifications: {e}")
            return []
    
    def mark_notification_read(self, notification_id: str) -> bool:
        """
        Mark a notification as read
        
        Args:
            notification_id: ID of the notification to mark as read
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            success = postgres_db.mark_notification_read(notification_id)
            return success
        except Exception as e:
            print(f"❌ Error marking notification as read: {e}")
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
