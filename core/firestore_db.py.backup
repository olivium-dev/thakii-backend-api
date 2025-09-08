import os
import uuid
import datetime
from typing import Optional, List, Dict, Any
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

load_dotenv()

# Initialize Firebase Admin SDK
def initialize_firestore():
    """Initialize Firestore with application default credentials or service account key"""
    # Check if Firebase is disabled
    if os.getenv('DISABLE_FIREBASE', '').lower() == 'true':
        print("📝 Firebase disabled via DISABLE_FIREBASE environment variable")
        return None
        
    try:
        if not firebase_admin._apps:
            # Try to use service account key file if provided
            service_account_path = os.getenv('FIREBASE_SERVICE_ACCOUNT_KEY')
            
            if service_account_path and os.path.exists(service_account_path):
                cred = credentials.Certificate(service_account_path)
                firebase_admin.initialize_app(cred)
            else:
                # Use application default credentials (for local development or GCP environments)
                firebase_admin.initialize_app()
        
        return firestore.client()
    except Exception as e:
        print(f"⚠️ Firebase initialization failed: {e}")
        print("📝 The service will continue without Firebase functionality")
        return None

class FirestoreDB:
    def __init__(self):
        self.db = initialize_firestore()
        self.collection_name = 'video_tasks'
    
    def _is_available(self):
        """Check if Firebase is available"""
        return self.db is not None
    
    def _handle_unavailable(self, operation_name: str):
        """Handle case when Firebase is not available"""
        print(f"⚠️ Firebase not available for operation: {operation_name}")
        return None
    
    def create_video_task(self, video_id: str, filename: str, user_id: str, user_email: str, status: str = "in_queue") -> Dict[str, Any]:
        """Create a new video task in Firestore"""
        if not self._is_available():
            return self._handle_unavailable("create_video_task")
            
        upload_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        task_data = {
            'video_id': video_id,
            'filename': filename,
            'user_id': user_id,
            'user_email': user_email,
            'upload_date': upload_date,
            'status': status,
            'created_at': firestore.SERVER_TIMESTAMP,
            'updated_at': firestore.SERVER_TIMESTAMP
        }
        
        # Add document with video_id as document ID for easy retrieval
        doc_ref = self.db.collection(self.collection_name).document(video_id)
        doc_ref.set(task_data)
        
        return task_data
    
    def get_video_task(self, video_id: str) -> Optional[Dict[str, Any]]:
        """Get a video task by video_id"""
        doc_ref = self.db.collection(self.collection_name).document(video_id)
        doc = doc_ref.get()
        
        if doc.exists:
            return doc.to_dict()
        return None
    
    def update_video_task_status(self, video_id: str, status: str) -> bool:
        """Update video task status"""
        doc_ref = self.db.collection(self.collection_name).document(video_id)
        
        try:
            doc_ref.update({
                'status': status,
                'updated_at': firestore.SERVER_TIMESTAMP
            })
            return True
        except Exception as e:
            print(f"Error updating video task status: {e}")
            return False
    
    def get_all_video_tasks(self) -> List[Dict[str, Any]]:
        """Get all video tasks ordered by creation date (admin only)"""
        docs = self.db.collection(self.collection_name).order_by('created_at', direction=firestore.Query.DESCENDING).stream()
        
        tasks = []
        for doc in docs:
            task_data = doc.to_dict()
            task_data['id'] = doc.id  # Include document ID
            tasks.append(task_data)  # Return the full task data
        
        return tasks
    
    def get_user_video_tasks(self, user_id: str) -> List[Dict[str, Any]]:
        """Get video tasks for a specific user ordered by creation date"""
        docs = self.db.collection(self.collection_name).where('user_id', '==', user_id).order_by('created_at', direction=firestore.Query.DESCENDING).stream()
        
        tasks = []
        for doc in docs:
            task_data = doc.to_dict()
            task_data['id'] = doc.id  # Include document ID
            tasks.append(task_data)
        
        return tasks
    
    def get_next_queued_task(self) -> Optional[Dict[str, Any]]:
        """Get the next task in queue (FIFO)"""
        try:
            docs = self.db.collection(self.collection_name).where('status', '==', 'in_queue').limit(1).get()
            
            if docs:
                doc = docs[0]
                task_data = doc.to_dict()
                task_data['id'] = doc.id  # Include document ID
                print(f"Found queued task: {doc.id}")
                return task_data
            
            return None
        except Exception as e:
            print(f"Error getting next queued task: {e}")
            return None
    
    def delete_video_task(self, video_id: str) -> bool:
        """Delete a video task"""
        try:
            self.db.collection(self.collection_name).document(video_id).delete()
            return True
        except Exception as e:
            print(f"Error deleting video task: {e}")
            return False
    
    def get_tasks_by_status(self, status: str) -> List[Dict[str, Any]]:
        """Get all tasks with a specific status"""
        docs = self.db.collection(self.collection_name).where('status', '==', status).stream()
        
        tasks = []
        for doc in docs:
            tasks.append(doc.to_dict())
        
        return tasks
    
    def get_admin_stats(self) -> Dict[str, Any]:
        """Get admin statistics"""
        try:
            # Get all tasks
            all_tasks = self.get_all_video_tasks()
            
            # Count unique users
            unique_users = set()
            status_counts = {}
            
            for task in all_tasks:
                if task.get('user_email'):
                    unique_users.add(task['user_email'])
                
                status = task.get('status', 'unknown')
                status_counts[status] = status_counts.get(status, 0) + 1
            
            return {
                'totalUsers': len(unique_users),
                'totalVideos': len(all_tasks),
                'totalPDFs': status_counts.get('done', 0),
                'activeProcessing': status_counts.get('in_progress', 0)
            }
        except Exception as e:
            print(f"Error getting admin stats: {e}")
            return {
                'totalUsers': 0,
                'totalVideos': 0,
                'totalPDFs': 0,
                'activeProcessing': 0
            }

# Global instance
firestore_db = FirestoreDB() 