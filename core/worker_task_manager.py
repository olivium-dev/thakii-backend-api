#!/usr/bin/env python3
"""
Worker Task Manager for Thakii Backend
Manages task assignment and worker coordination via API
"""

import os
import datetime
import time
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

load_dotenv()

# Feature flag for worker API
ENABLE_WORKER_API = os.getenv('ENABLE_WORKER_API', 'false').lower() == 'true'

# Worker heartbeat timeout (seconds)
WORKER_HEARTBEAT_TIMEOUT = int(os.getenv('WORKER_HEARTBEAT_TIMEOUT', '300'))  # 5 minutes

class WorkerTaskManager:
    def __init__(self, postgres_db):
        """Initialize with PostgresDB instance"""
        self.postgres_db = postgres_db
        self.is_enabled = ENABLE_WORKER_API
        print(f"🔧 Worker Task Manager initialized. API enabled: {self.is_enabled}")
        
    def pickup_task(self, worker_id: str, worker_capacity: int = 4) -> Optional[Dict[str, Any]]:
        """
        Atomically pick up a task for processing
        
        Args:
            worker_id: Unique identifier for the worker
            worker_capacity: Maximum number of concurrent tasks the worker can handle
            
        Returns:
            Task object or None if no tasks available
        """
        if not self.is_enabled:
            print("⚠️ Worker API is disabled. Task pickup via API not available.")
            return None
            
        # Check worker's current task count
        current_tasks = self._get_worker_active_tasks(worker_id)
        if len(current_tasks) >= worker_capacity:
            print(f"⚠️ Worker {worker_id} at capacity ({len(current_tasks)}/{worker_capacity})")
            return None
        
        # Get a connection from the pool
        conn = self.postgres_db.pool.getconn()
        try:
            # Use transaction with row-level locking to prevent race conditions
            with conn.cursor(cursor_factory=self.postgres_db.RealDictCursor) as cur:
                # Begin transaction
                cur.execute("BEGIN")
                
                # Find oldest unassigned task with FOR UPDATE SKIP LOCKED
                # This prevents multiple workers from picking up the same task
                cur.execute("""
                    SELECT * FROM video_tasks 
                    WHERE status IN ('in_queue', 'uploaded')
                      AND (assigned_worker IS NULL OR 
                           (last_heartbeat < NOW() - INTERVAL '%s seconds'))
                    ORDER BY created_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                """, (WORKER_HEARTBEAT_TIMEOUT,))
                
                task = cur.fetchone()
                if not task:
                    # No tasks available, rollback transaction
                    conn.rollback()
                    return None
                
                # Update task with worker assignment
                video_id = task['video_id']
                now = datetime.datetime.now()
                
                cur.execute("""
                    UPDATE video_tasks
                    SET status = 'processing',
                        assigned_worker = %s,
                        assignment_time = %s,
                        last_heartbeat = %s,
                        processing_start = %s,
                        updated_at = %s
                    WHERE video_id = %s
                """, (worker_id, now, now, now, now, video_id))
                
                # Commit transaction
                conn.commit()
                
                # Convert to dict and format datetime objects
                task_dict = dict(task)
                for key, value in task_dict.items():
                    if isinstance(value, datetime.datetime):
                        task_dict[key] = value.isoformat()
                
                print(f"✅ Task {video_id} assigned to worker {worker_id}")
                return task_dict
                
        except Exception as e:
            # Rollback on error
            conn.rollback()
            print(f"❌ Error in pickup_task: {e}")
            return None
        finally:
            # Return connection to pool
            self.postgres_db.pool.putconn(conn)
    
    def update_task(self, video_id: str, worker_id: str, status: str, 
                   progress: int = None, pdf_url: str = None, 
                   error_message: str = None) -> bool:
        """
        Update task status and metadata
        
        Args:
            video_id: Task identifier
            worker_id: Worker identifier (must match assigned worker)
            status: New task status
            progress: Processing progress (0-100)
            pdf_url: URL to generated PDF
            error_message: Error message if failed
            
        Returns:
            bool: Success or failure
        """
        if not self.is_enabled:
            print("⚠️ Worker API is disabled. Using legacy update method.")
            updates = {'status': status}
            if progress is not None:
                updates['progress_percentage'] = progress
            if pdf_url is not None:
                updates['pdf_url'] = pdf_url
            if error_message is not None:
                updates['error_message'] = error_message
            return self.postgres_db.update_video_task(video_id, updates)
        
        # Get current task state
        task = self.postgres_db.get_video_task(video_id)
        if not task:
            print(f"❌ Task {video_id} not found")
            return False
            
        # Verify worker assignment
        assigned_worker = task.get('assigned_worker')
        if assigned_worker != worker_id:
            print(f"❌ Worker mismatch: {worker_id} vs {assigned_worker}")
            return False
        
        # Prepare updates
        updates = {
            'status': status,
            'updated_at': datetime.datetime.now(),
            'last_heartbeat': datetime.datetime.now()
        }
        
        # Add optional fields
        if progress is not None:
            updates['progress_percentage'] = progress
        
        if pdf_url is not None:
            updates['pdf_url'] = pdf_url
        
        if error_message is not None:
            updates['error_message'] = error_message
        
        # Add timing fields based on status
        if status in ['completed', 'done', 'failed']:
            updates['processing_end'] = datetime.datetime.now()
        
        # Update database
        return self.postgres_db.update_video_task(video_id, updates)
    
    def worker_heartbeat(self, worker_id: str, active_tasks: List[str]) -> bool:
        """
        Update heartbeat timestamp for worker's active tasks
        
        Args:
            worker_id: Worker identifier
            active_tasks: List of video_ids being processed
            
        Returns:
            bool: Success or failure
        """
        if not self.is_enabled:
            print("⚠️ Worker API is disabled. Heartbeat not recorded.")
            return False
            
        if not active_tasks:
            return True  # Nothing to do
            
        # Get a connection from the pool
        conn = self.postgres_db.pool.getconn()
        try:
            with conn.cursor() as cur:
                # Update heartbeat for all active tasks
                cur.execute("""
                    UPDATE video_tasks
                    SET last_heartbeat = %s
                    WHERE video_id IN %s
                      AND assigned_worker = %s
                """, (datetime.datetime.now(), tuple(active_tasks), worker_id))
                
                conn.commit()
                return cur.rowcount > 0
                
        except Exception as e:
            conn.rollback()
            print(f"❌ Error in worker_heartbeat: {e}")
            return False
        finally:
            self.postgres_db.pool.putconn(conn)
    
    def _get_worker_active_tasks(self, worker_id: str) -> List[Dict[str, Any]]:
        """
        Get active tasks for a worker
        
        Args:
            worker_id: Worker identifier
            
        Returns:
            List of active tasks
        """
        conn = self.postgres_db.pool.getconn()
        try:
            with conn.cursor(cursor_factory=self.postgres_db.RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM video_tasks
                    WHERE assigned_worker = %s
                      AND status = 'processing'
                """, (worker_id,))
                
                tasks = []
                for row in cur.fetchall():
                    task = dict(row)
                    for key, value in task.items():
                        if isinstance(value, datetime.datetime):
                            task[key] = value.isoformat()
                    tasks.append(task)
                
                return tasks
                
        except Exception as e:
            print(f"❌ Error getting worker tasks: {e}")
            return []
        finally:
            self.postgres_db.pool.putconn(conn)
    
    def recover_stale_tasks(self) -> int:
        """
        Reset stale tasks to 'in_queue' status
        Tasks are considered stale if heartbeat is older than timeout
        
        Returns:
            int: Number of tasks recovered
        """
        if not self.is_enabled:
            return 0
            
        conn = self.postgres_db.pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE video_tasks
                    SET status = 'in_queue',
                        assigned_worker = NULL,
                        assignment_time = NULL,
                        last_heartbeat = NULL,
                        updated_at = %s
                    WHERE status = 'processing'
                      AND last_heartbeat < NOW() - INTERVAL '%s seconds'
                    RETURNING video_id
                """, (datetime.datetime.now(), WORKER_HEARTBEAT_TIMEOUT))
                
                recovered = cur.fetchall()
                conn.commit()
                
                if recovered:
                    video_ids = [r[0] for r in recovered]
                    print(f"🔄 Recovered {len(video_ids)} stale tasks: {video_ids}")
                
                return len(recovered)
                
        except Exception as e:
            conn.rollback()
            print(f"❌ Error recovering stale tasks: {e}")
            return 0
        finally:
            self.postgres_db.pool.putconn(conn)

# Create singleton instance
worker_task_manager = None

def init_worker_task_manager(postgres_db):
    """Initialize the worker task manager with PostgresDB instance"""
    global worker_task_manager
    worker_task_manager = WorkerTaskManager(postgres_db)
    return worker_task_manager

def get_worker_task_manager():
    """Get the worker task manager instance"""
    global worker_task_manager
    if worker_task_manager is None:
        raise RuntimeError("Worker task manager not initialized")
    return worker_task_manager
