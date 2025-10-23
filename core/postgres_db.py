#!/usr/bin/env python3
"""
PostgreSQL Database Layer for Thakii Backend
Replaces Firebase Firestore with PostgreSQL
"""

import os
import psycopg2
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import RealDictCursor, Json
from typing import Optional, List, Dict, Any
import datetime
from dotenv import load_dotenv

load_dotenv()

class PostgresDB:
    def __init__(self):
        """Initialize PostgreSQL connection pool"""
        self.pool = self._create_connection_pool()
        
    def _create_connection_pool(self) -> SimpleConnectionPool:
        """Create connection pool for PostgreSQL"""
        try:
            pool = SimpleConnectionPool(
                minconn=1,
                maxconn=20,
                host=os.getenv('POSTGRES_HOST', 'localhost'),
                port=os.getenv('POSTGRES_PORT', '5432'),
                database=os.getenv('POSTGRES_DB', 'thakii_production'),
                user=os.getenv('POSTGRES_USER', 'thakii_user'),
                password=os.getenv('POSTGRES_PASSWORD')
            )
            print("✅ PostgreSQL connection pool created successfully")
            return pool
        except Exception as e:
            print(f"❌ Failed to create PostgreSQL connection pool: {e}")
            raise
    
    def _is_available(self) -> bool:
        """Check if PostgreSQL is available"""
        return self.pool is not None
    
    # ========== VIDEO TASKS OPERATIONS ==========
    
    def create_video_task(self, video_id: str, filename: str, 
                         user_id: str, user_email: str, 
                         status: str = "in_queue") -> Dict[str, Any]:
        """Create a new video task"""
        if not self._is_available():
            raise Exception("PostgreSQL not available")
            
        conn = self.pool.getconn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO video_tasks 
                    (video_id, filename, user_id, user_email, status, upload_date)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING *
                """, (video_id, filename, user_id, user_email, status, 
                      datetime.datetime.now()))
                conn.commit()
                result = dict(cur.fetchone())
                # Convert datetime objects to ISO format strings
                for key, value in result.items():
                    if isinstance(value, datetime.datetime):
                        result[key] = value.isoformat()
                return result
        finally:
            self.pool.putconn(conn)
    
    def get_video_task(self, video_id: str) -> Optional[Dict[str, Any]]:
        """Get a video task by video_id"""
        if not self._is_available():
            return None
            
        conn = self.pool.getconn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM video_tasks 
                    WHERE video_id = %s
                """, (video_id,))
                result = cur.fetchone()
                if result:
                    result = dict(result)
                    # Convert datetime objects to ISO format strings
                    for key, value in result.items():
                        if isinstance(value, datetime.datetime):
                            result[key] = value.isoformat()
                    return result
                return None
        finally:
            self.pool.putconn(conn)
    
    def update_video_task(self, video_id: str, updates: Dict[str, Any]) -> bool:
        """Update video task with provided fields"""
        if not self._is_available():
            return False
            
        conn = self.pool.getconn()
        try:
            with conn.cursor() as cur:
                # Build dynamic UPDATE query
                set_clauses = []
                values = []
                
                for key, value in updates.items():
                    set_clauses.append(f"{key} = %s")
                    values.append(value)
                
                # Add video_id to values for WHERE clause
                values.append(video_id)
                
                query = f"""
                    UPDATE video_tasks 
                    SET {', '.join(set_clauses)}
                    WHERE video_id = %s
                """
                
                cur.execute(query, values)
                conn.commit()
                return cur.rowcount > 0
        finally:
            self.pool.putconn(conn)
    
    def get_all_video_tasks(self) -> List[Dict[str, Any]]:
        """Get all video tasks ordered by creation date (admin only)"""
        if not self._is_available():
            return []
            
        conn = self.pool.getconn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM video_tasks 
                    ORDER BY created_at DESC
                """)
                results = cur.fetchall()
                tasks = []
                for result in results:
                    task = dict(result)
                    # Convert datetime objects to ISO format strings
                    for key, value in task.items():
                        if isinstance(value, datetime.datetime):
                            task[key] = value.isoformat()
                    tasks.append(task)
                return tasks
        finally:
            self.pool.putconn(conn)
    
    def get_user_video_tasks(self, user_id: str) -> List[Dict[str, Any]]:
        """Get video tasks for a specific user ordered by creation date"""
        if not self._is_available():
            return []
            
        conn = self.pool.getconn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM video_tasks 
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                """, (user_id,))
                results = cur.fetchall()
                tasks = []
                for result in results:
                    task = dict(result)
                    # Convert datetime objects to ISO format strings
                    for key, value in task.items():
                        if isinstance(value, datetime.datetime):
                            task[key] = value.isoformat()
                    tasks.append(task)
                return tasks
        finally:
            self.pool.putconn(conn)
    
    def get_next_queued_task(self) -> Optional[Dict[str, Any]]:
        """Get the next task in queue (FIFO)"""
        if not self._is_available():
            return None
            
        conn = self.pool.getconn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM video_tasks 
                    WHERE status = 'in_queue'
                    ORDER BY created_at ASC
                    LIMIT 1
                """)
                result = cur.fetchone()
                if result:
                    task = dict(result)
                    # Convert datetime objects to ISO format strings
                    for key, value in task.items():
                        if isinstance(value, datetime.datetime):
                            task[key] = value.isoformat()
                    return task
                return None
        finally:
            self.pool.putconn(conn)
    
    def delete_video_task(self, video_id: str) -> bool:
        """Delete a video task"""
        if not self._is_available():
            return False
            
        conn = self.pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    DELETE FROM video_tasks 
                    WHERE video_id = %s
                """, (video_id,))
                conn.commit()
                return cur.rowcount > 0
        finally:
            self.pool.putconn(conn)
    
    def get_tasks_by_status(self, status: str) -> List[Dict[str, Any]]:
        """Get all tasks with a specific status"""
        if not self._is_available():
            return []
            
        conn = self.pool.getconn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM video_tasks 
                    WHERE status = %s
                    ORDER BY created_at DESC
                """, (status,))
                results = cur.fetchall()
                tasks = []
                for result in results:
                    task = dict(result)
                    # Convert datetime objects to ISO format strings
                    for key, value in task.items():
                        if isinstance(value, datetime.datetime):
                            task[key] = value.isoformat()
                    tasks.append(task)
                return tasks
        finally:
            self.pool.putconn(conn)
    
    def get_admin_stats(self) -> Dict[str, Any]:
        """Get admin statistics"""
        if not self._is_available():
            return {
                'totalUsers': 0,
                'totalVideos': 0,
                'totalPDFs': 0,
                'activeProcessing': 0
            }
            
        conn = self.pool.getconn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get total unique users
                cur.execute("SELECT COUNT(DISTINCT user_id) as count FROM video_tasks")
                total_users = cur.fetchone()['count']
                
                # Get total videos
                cur.execute("SELECT COUNT(*) as count FROM video_tasks")
                total_videos = cur.fetchone()['count']
                
                # Get completed PDFs
                cur.execute("SELECT COUNT(*) as count FROM video_tasks WHERE status IN ('done', 'completed')")
                total_pdfs = cur.fetchone()['count']
                
                # Get active processing
                cur.execute("SELECT COUNT(*) as count FROM video_tasks WHERE status IN ('in_progress', 'processing')")
                active_processing = cur.fetchone()['count']
                
                return {
                    'totalUsers': total_users,
                    'totalVideos': total_videos,
                    'totalPDFs': total_pdfs,
                    'activeProcessing': active_processing
                }
        finally:
            self.pool.putconn(conn)
    
    # ========== ADMIN USERS OPERATIONS ==========
    
    def get_admin_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get admin user by email"""
        conn = self.pool.getconn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM admin_users WHERE email = %s", (email,))
                result = cur.fetchone()
                if result:
                    admin = dict(result)
                    for key, value in admin.items():
                        if isinstance(value, datetime.datetime):
                            admin[key] = value.isoformat()
                    return admin
                return None
        finally:
            self.pool.putconn(conn)
    
    def get_all_admins(self) -> List[Dict[str, Any]]:
        """Get all admin users"""
        conn = self.pool.getconn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM admin_users ORDER BY created_at DESC")
                results = cur.fetchall()
                admins = []
                for result in results:
                    admin = dict(result)
                    for key, value in admin.items():
                        if isinstance(value, datetime.datetime):
                            admin[key] = value.isoformat()
                    admins.append(admin)
                return admins
        finally:
            self.pool.putconn(conn)
    
    def create_admin(self, email: str, role: str, status: str, 
                    is_super_admin: bool, description: str, added_by: str) -> Dict[str, Any]:
        """Create a new admin user"""
        conn = self.pool.getconn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO admin_users 
                    (email, role, status, is_super_admin, description, added_by)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING *
                """, (email, role, status, is_super_admin, description, added_by))
                conn.commit()
                result = dict(cur.fetchone())
                for key, value in result.items():
                    if isinstance(value, datetime.datetime):
                        result[key] = value.isoformat()
                return result
        finally:
            self.pool.putconn(conn)
    
    def update_admin(self, admin_id: str, updates: Dict[str, Any]) -> bool:
        """Update admin user"""
        conn = self.pool.getconn()
        try:
            with conn.cursor() as cur:
                set_clauses = []
                values = []
                
                for key, value in updates.items():
                    set_clauses.append(f"{key} = %s")
                    values.append(value)
                
                values.append(admin_id)
                
                query = f"""
                    UPDATE admin_users 
                    SET {', '.join(set_clauses)}
                    WHERE id = %s
                """
                
                cur.execute(query, values)
                conn.commit()
                return cur.rowcount > 0
        finally:
            self.pool.putconn(conn)
    
    def delete_admin(self, admin_id: str) -> bool:
        """Delete an admin user"""
        conn = self.pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM admin_users WHERE id = %s", (admin_id,))
                conn.commit()
                return cur.rowcount > 0
        finally:
            self.pool.putconn(conn)
    
    # ========== PROCESSING SERVERS OPERATIONS ==========
    
    def get_all_servers(self) -> List[Dict[str, Any]]:
        """Get all processing servers"""
        conn = self.pool.getconn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM processing_servers ORDER BY created_at DESC")
                results = cur.fetchall()
                servers = []
                for result in results:
                    server = dict(result)
                    for key, value in server.items():
                        if isinstance(value, datetime.datetime):
                            server[key] = value.isoformat()
                    servers.append(server)
                return servers
        finally:
            self.pool.putconn(conn)
    
    def create_server(self, name: str, url: str, server_type: str, 
                     status: str, description: str, health_status: Dict) -> Dict[str, Any]:
        """Create a new processing server"""
        conn = self.pool.getconn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO processing_servers 
                    (name, url, type, status, description, health_status)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING *
                """, (name, url, server_type, status, description, Json(health_status)))
                conn.commit()
                result = dict(cur.fetchone())
                for key, value in result.items():
                    if isinstance(value, datetime.datetime):
                        result[key] = value.isoformat()
                return result
        finally:
            self.pool.putconn(conn)
    
    def update_server(self, server_id: str, updates: Dict[str, Any]) -> bool:
        """Update processing server"""
        conn = self.pool.getconn()
        try:
            with conn.cursor() as cur:
                set_clauses = []
                values = []
                
                for key, value in updates.items():
                    if key == 'health_status' and isinstance(value, dict):
                        set_clauses.append(f"{key} = %s")
                        values.append(Json(value))
                    else:
                        set_clauses.append(f"{key} = %s")
                        values.append(value)
                
                values.append(server_id)
                
                query = f"""
                    UPDATE processing_servers 
                    SET {', '.join(set_clauses)}
                    WHERE id = %s
                """
                
                cur.execute(query, values)
                conn.commit()
                return cur.rowcount > 0
        finally:
            self.pool.putconn(conn)
    
    def delete_server(self, server_id: str) -> bool:
        """Delete a processing server"""
        conn = self.pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM processing_servers WHERE id = %s", (server_id,))
                conn.commit()
                return cur.rowcount > 0
        finally:
            self.pool.putconn(conn)
    
    # ========== NOTIFICATIONS OPERATIONS ==========
    
    def create_notification(self, user_id: str, title: str, body: str, 
                           notification_type: str, data: Optional[Dict] = None) -> Dict[str, Any]:
        """Create a new notification"""
        conn = self.pool.getconn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO notifications 
                    (user_id, title, body, type, data)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING *
                """, (user_id, title, body, notification_type, Json(data or {})))
                conn.commit()
                result = dict(cur.fetchone())
                for key, value in result.items():
                    if isinstance(value, datetime.datetime):
                        result[key] = value.isoformat()
                return result
        finally:
            self.pool.putconn(conn)
    
    def get_user_notifications(self, user_id: str, unread_only: bool = False) -> List[Dict[str, Any]]:
        """Get notifications for a user"""
        conn = self.pool.getconn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if unread_only:
                    cur.execute("""
                        SELECT * FROM notifications 
                        WHERE user_id = %s AND read = FALSE
                        ORDER BY created_at DESC
                    """, (user_id,))
                else:
                    cur.execute("""
                        SELECT * FROM notifications 
                        WHERE user_id = %s
                        ORDER BY created_at DESC
                    """, (user_id,))
                
                results = cur.fetchall()
                notifications = []
                for result in results:
                    notification = dict(result)
                    for key, value in notification.items():
                        if isinstance(value, datetime.datetime):
                            notification[key] = value.isoformat()
                    notifications.append(notification)
                return notifications
        finally:
            self.pool.putconn(conn)
    
    def mark_notification_read(self, notification_id: str) -> bool:
        """Mark a notification as read"""
        conn = self.pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE notifications 
                    SET read = TRUE
                    WHERE id = %s
                """, (notification_id,))
                conn.commit()
                return cur.rowcount > 0
        finally:
            self.pool.putconn(conn)
    
    def __del__(self):
        """Clean up connection pool"""
        if hasattr(self, 'pool') and self.pool:
            self.pool.closeall()


# Global instance
postgres_db = PostgresDB()




