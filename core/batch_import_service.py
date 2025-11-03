#!/usr/bin/env python3
"""
Batch Import Service for wolkesicher.de (Nextcloud) shares
Downloads videos directly from WebDAV shares and imports them into the system
New architecture: Job-based processing with database tables
"""

import requests
import xml.etree.ElementTree as ET
import re
import uuid
import io
import time
import threading
from pathlib import Path
from urllib.parse import urlparse, unquote
from typing import List, Dict, Optional
from werkzeug.datastructures import FileStorage
from datetime import datetime


class BatchImportService:
    """Service for importing videos from wolkesicher.de Nextcloud shares"""
    
    def __init__(self, postgres_db=None, s3_storage=None, websocket_manager=None, trigger_worker_fn=None):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Thakii-BatchImport/1.0'
        })
        
        # Dependencies for database-driven processing
        self.postgres_db = postgres_db
        self.s3_storage = s3_storage
        self.websocket_manager = websocket_manager
        self.trigger_worker_fn = trigger_worker_fn
        
        # Background processing control
        self.running = False
        self.poll_interval = 10  # seconds
        self.max_concurrent_downloads = 2
    
    def extract_base_url(self, url: str) -> str:
        """Extract base URL from share URL"""
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"
    
    def extract_share_token(self, url: str) -> str:
        """Extract share token from URL (format: /s/TOKEN)"""
        # Handle URLs with query parameters like ?path=...
        base_url = url.split('?')[0]  # Remove query parameters for token extraction
        match = re.search(r'/s/([^/]+)', base_url)
        if match:
            return match.group(1)
        raise ValueError(f"Could not extract share token from URL: {url}")
    
    def extract_path_from_url(self, url: str) -> str:
        """Extract path parameter from URL if present"""
        from urllib.parse import urlparse, parse_qs, unquote
        parsed = urlparse(url)
        if parsed.query:
            query_params = parse_qs(parsed.query)
            if 'path' in query_params:
                # Decode the URL-encoded path
                path = unquote(query_params['path'][0])
                # Remove leading slash if present
                return path.lstrip('/')
        return ""
    
    def is_video_file(self, filename: str) -> bool:
        """Check if file is a video based on extension"""
        video_extensions = {'.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', 
                          '.webm', '.m4v', '.3gp', '.ogv', '.m2ts', '.ts'}
        return Path(filename).suffix.lower() in video_extensions
    
    def list_videos_from_share(self, share_url: str) -> Dict:
        """
        List all video files from a wolkesicher.de share
        
        Args:
            share_url: The Nextcloud share URL
            
        Returns:
            Dict with 'videos' list, 'total_count', and 'total_size'
        """
        print(f"📋 Listing videos from share: {share_url}")
        
        try:
            base_url = self.extract_base_url(share_url)
            share_token = self.extract_share_token(share_url)
            path = self.extract_path_from_url(share_url)
            
            # Build WebDAV URL with path if present
            webdav_url = f"{base_url}/public.php/webdav/"
            if path:
                webdav_url += path + "/"
            
            print(f"   Base URL: {base_url}")
            print(f"   Share Token: {share_token}")
            print(f"   Path: {path}")
            print(f"   WebDAV URL: {webdav_url}")
            
            # WebDAV authentication: token as username, empty password
            auth = (share_token, "")
            
            # PROPFIND request to list files
            headers = {
                'Depth': '1',
                'Content-Type': 'text/xml'
            }
            
            propfind_body = '''<?xml version="1.0"?>
            <d:propfind xmlns:d="DAV:">
                <d:prop>
                    <d:displayname/>
                    <d:getcontentlength/>
                    <d:getcontenttype/>
                    <d:getlastmodified/>
                    <d:resourcetype/>
                </d:prop>
            </d:propfind>'''
            
            response = self.session.request(
                'PROPFIND',
                webdav_url,
                headers=headers,
                data=propfind_body,
                auth=auth,
                timeout=60
            )
            
            print(f"   WebDAV Response: {response.status_code}")
            
            if response.status_code == 207:  # Multi-Status
                files = self._parse_webdav_response(response.text, webdav_url)
                video_files = [f for f in files if f['is_video']]
                
                total_size = sum(v['size'] for v in video_files)
                
                print(f"   ✅ Found {len(video_files)} video files")
                print(f"   📊 Total size: {total_size / 1024 / 1024:.1f} MB")
                
                return {
                    'videos': video_files,
                    'total_count': len(video_files),
                    'total_size': total_size
                }
            else:
                print(f"   ❌ WebDAV failed with status {response.status_code}")
                return {
                    'videos': [],
                    'total_count': 0,
                    'total_size': 0,
                    'error': f"Failed to list videos: HTTP {response.status_code}"
                }
                
        except Exception as e:
            print(f"❌ Error listing videos: {e}")
            import traceback
            traceback.print_exc()
            return {
                'videos': [],
                'total_count': 0,
                'total_size': 0,
                'error': str(e)
            }
    
    def _parse_webdav_response(self, xml_content: str, webdav_url: str) -> List[Dict]:
        """Parse WebDAV PROPFIND XML response"""
        files = []
        try:
            root = ET.fromstring(xml_content)
            
            for response in root.findall('.//{DAV:}response'):
                href = response.find('.//{DAV:}href')
                displayname = response.find('.//{DAV:}displayname')
                contentlength = response.find('.//{DAV:}getcontentlength')
                contenttype = response.find('.//{DAV:}getcontenttype')
                resourcetype = response.find('.//{DAV:}resourcetype')
                
                if href is not None and displayname is not None:
                    # Skip directories
                    if (resourcetype is not None and 
                        resourcetype.find('.//{DAV:}collection') is not None):
                        continue
                    
                    filename = displayname.text
                    if filename and filename != '/' and filename.strip():
                        file_info = {
                            'name': filename,
                            'size': int(contentlength.text) if contentlength is not None and contentlength.text else 0,
                            'type': contenttype.text if contenttype is not None else 'unknown',
                            'is_video': self.is_video_file(filename),
                            'download_url': f"{webdav_url}{filename}"
                        }
                        files.append(file_info)
            
            return files
            
        except Exception as e:
            print(f"❌ Error parsing WebDAV response: {e}")
            return []
    
    def download_and_import_video(
        self, 
        share_url: str, 
        video_info: Dict,
        user_id: str,
        user_email: str,
        s3_storage,
        postgres_db,
        websocket_manager=None,
        trigger_worker_fn=None
    ) -> Optional[Dict]:
        """
        Download video from wolkesicher.de and import it
        
        Args:
            share_url: The Nextcloud share URL
            video_info: Video metadata dict with 'name', 'download_url', 'size'
            user_id: User ID
            user_email: User email
            s3_storage: S3Storage instance
            postgres_db: PostgresDB instance
            websocket_manager: WebSocketManager instance (optional)
            trigger_worker_fn: Function to trigger worker processing (optional)
            
        Returns:
            Dict with video_id and status, or None if failed
        """
        video_name = video_info['name']
        video_id = str(uuid.uuid4())
        
        print(f"\n📥 Importing video: {video_name}")
        print(f"   Video ID: {video_id}")
        print(f"   Size: {video_info['size'] / 1024 / 1024:.1f} MB")
        
        try:
            # Notify: Starting download
            if websocket_manager:
                websocket_manager.notify_batch_import_progress(user_id, {
                    'video_name': video_name,
                    'video_id': video_id,
                    'status': 'downloading',
                    'progress_percent': 0
                })
            
            # Extract authentication
            share_token = self.extract_share_token(share_url)
            auth = (share_token, "")
            
            # Download video via WebDAV with streaming
            print(f"   🌐 Downloading from: {video_info['download_url']}")
            response = self.session.get(
                video_info['download_url'],
                auth=auth,
                stream=True,
                timeout=300
            )
            response.raise_for_status()
            
            # Create file-like object for S3 upload
            video_data = io.BytesIO()
            downloaded = 0
            total_size = int(response.headers.get('content-length', video_info['size']))
            
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    video_data.write(chunk)
                    downloaded += len(chunk)
                    
                    # Update progress every 5MB
                    if downloaded % (5 * 1024 * 1024) == 0:
                        progress = int((downloaded / total_size) * 50)  # 0-50% for download
                        if websocket_manager:
                            websocket_manager.notify_batch_import_progress(user_id, {
                                'video_name': video_name,
                                'video_id': video_id,
                                'status': 'downloading',
                                'progress_percent': progress
                            })
            
            video_data.seek(0)
            print(f"   ✅ Downloaded: {downloaded / 1024 / 1024:.1f} MB")
            
            # Notify: Starting upload to S3
            if websocket_manager:
                websocket_manager.notify_batch_import_progress(user_id, {
                    'video_name': video_name,
                    'video_id': video_id,
                    'status': 'uploading',
                    'progress_percent': 50
                })
            
            # Upload to S3
            print(f"   ☁️  Uploading to S3...")
            
            # Create FileStorage-like object for S3 upload
            file_storage = FileStorage(
                stream=video_data,
                filename=video_name,
                content_type=video_info.get('type', 'video/mp4')
            )
            
            s3_key = s3_storage.upload_video(file_storage, video_id, video_name)
            print(f"   ✅ Uploaded to S3: {s3_key}")
            
            # Notify: Creating task
            if websocket_manager:
                websocket_manager.notify_batch_import_progress(user_id, {
                    'video_name': video_name,
                    'video_id': video_id,
                    'status': 'queued',
                    'progress_percent': 75
                })
            
            # Create task in database
            task_data = postgres_db.create_video_task(
                video_id,
                video_name,
                user_id,
                user_email,
                "in_queue",
                s3_key=s3_key
            )
            print(f"   ✅ Task created in database")
            
            # Trigger worker processing
            if trigger_worker_fn:
                trigger_success = trigger_worker_fn(
                    video_id=video_id,
                    user_id=user_id,
                    filename=video_name,
                    s3_key=s3_key
                )
                if not trigger_success:
                    print(f"   ⚠️  Worker trigger failed")
            
            # Notify: Completed
            if websocket_manager:
                websocket_manager.notify_batch_import_progress(user_id, {
                    'video_name': video_name,
                    'video_id': video_id,
                    'status': 'completed',
                    'progress_percent': 100
                })
                
                # Also send regular task update
                websocket_manager.notify_task_update(user_id, {
                    'video_id': video_id,
                    'status': 'in_queue',
                    'filename': video_name
                })
            
            print(f"   🎉 Import completed successfully")
            
            return {
                'video_id': video_id,
                'video_name': video_name,
                'status': 'success',
                's3_key': s3_key
            }
            
        except Exception as e:
            print(f"   ❌ Import failed: {e}")
            import traceback
            traceback.print_exc()
            
            # Notify: Failed
            if websocket_manager:
                websocket_manager.notify_batch_import_progress(user_id, {
                    'video_name': video_name,
                    'video_id': video_id,
                    'status': 'failed',
                    'progress_percent': 0,
                    'error': str(e)
                })
            
            return {
                'video_id': video_id,
                'video_name': video_name,
                'status': 'failed',
                'error': str(e)
            }
    
    # ========== NEW DATABASE-DRIVEN METHODS ==========
    
    def create_batch_job(self, user_id: str, user_email: str, share_url: str) -> Optional[Dict]:
        """
        Create a batch import job with video records in database
        
        Args:
            user_id: User ID
            user_email: User email
            share_url: Nextcloud share URL
            
        Returns:
            Dict with job_id and video count, or None if failed
        """
        if not self.postgres_db:
            raise ValueError("PostgreSQL database not configured")
        
        print(f"🎯 Creating batch job for user: {user_email}")
        print(f"   Share URL: {share_url}")
        
        try:
            # List videos from share
            video_list = self.list_videos_from_share(share_url)
            if 'error' in video_list:
                return None
            
            videos = video_list['videos']
            if not videos:
                print("   ⚠️  No videos found in share")
                return None
            
            # Create batch job record
            job_id = str(uuid.uuid4())
            conn = self.postgres_db.pool.getconn()
            
            try:
                with conn.cursor() as cursor:
                    # Insert batch job
                    cursor.execute("""
                        INSERT INTO batch_import_jobs 
                        (id, user_id, user_email, share_url, status, total_videos)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (job_id, user_id, user_email, share_url, 'pending', len(videos)))
                    
                    # Insert video records
                    for video in videos:
                        cursor.execute("""
                            INSERT INTO batch_import_videos 
                            (batch_job_id, video_name, video_size, download_url, status)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (job_id, video['name'], video['size'], video['download_url'], 'queued'))
                    
                    conn.commit()
                    print(f"   ✅ Created batch job: {job_id}")
                    print(f"   📊 Videos queued: {len(videos)}")
                    
                    return {
                        'job_id': job_id,
                        'total_videos': len(videos),
                        'total_size': video_list['total_size']
                    }
                    
            finally:
                self.postgres_db.pool.putconn(conn)
                
        except Exception as e:
            print(f"❌ Error creating batch job: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def get_batch_job_status(self, job_id: str, user_id: str) -> Optional[Dict]:
        """
        Get status of a batch import job
        
        Args:
            job_id: Batch job ID
            user_id: User ID (for security)
            
        Returns:
            Dict with job status and video details
        """
        if not self.postgres_db:
            raise ValueError("PostgreSQL database not configured")
        
        conn = self.postgres_db.pool.getconn()
        
        try:
            with conn.cursor() as cursor:
                # Get job info
                cursor.execute("""
                    SELECT id, user_id, user_email, share_url, status, total_videos,
                           processed_videos, failed_videos, created_at, updated_at,
                           started_at, completed_at, error_message
                    FROM batch_import_jobs 
                    WHERE id = %s AND user_id = %s
                """, (job_id, user_id))
                
                job_row = cursor.fetchone()
                if not job_row:
                    return None
                
                # Get video details
                cursor.execute("""
                    SELECT id, video_name, video_size, status, video_id, s3_key,
                           progress_percent, error_message, created_at, updated_at,
                           download_started_at, download_completed_at
                    FROM batch_import_videos 
                    WHERE batch_job_id = %s
                    ORDER BY created_at
                """, (job_id,))
                
                video_rows = cursor.fetchall()
                
                # Format response
                job_data = {
                    'job_id': job_row[0],
                    'user_id': job_row[1],
                    'user_email': job_row[2],
                    'share_url': job_row[3],
                    'status': job_row[4],
                    'total_videos': job_row[5],
                    'processed_videos': job_row[6],
                    'failed_videos': job_row[7],
                    'created_at': job_row[8].isoformat() if job_row[8] else None,
                    'updated_at': job_row[9].isoformat() if job_row[9] else None,
                    'started_at': job_row[10].isoformat() if job_row[10] else None,
                    'completed_at': job_row[11].isoformat() if job_row[11] else None,
                    'error_message': job_row[12],
                    'videos': []
                }
                
                for video_row in video_rows:
                    video_data = {
                        'id': video_row[0],
                        'video_name': video_row[1],
                        'video_size': video_row[2],
                        'status': video_row[3],
                        'video_id': video_row[4],
                        's3_key': video_row[5],
                        'progress_percent': video_row[6],
                        'error_message': video_row[7],
                        'created_at': video_row[8].isoformat() if video_row[8] else None,
                        'updated_at': video_row[9].isoformat() if video_row[9] else None,
                        'download_started_at': video_row[10].isoformat() if video_row[10] else None,
                        'download_completed_at': video_row[11].isoformat() if video_row[11] else None
                    }
                    job_data['videos'].append(video_data)
                
                return job_data
                
        except Exception as e:
            print(f"❌ Error getting batch job status: {e}")
            return None
        finally:
            self.postgres_db.pool.putconn(conn)
    
    def list_user_batch_jobs(self, user_id: str, limit: int = 20) -> List[Dict]:
        """
        List batch import jobs for a user
        
        Args:
            user_id: User ID
            limit: Maximum number of jobs to return
            
        Returns:
            List of job summaries
        """
        if not self.postgres_db:
            raise ValueError("PostgreSQL database not configured")
        
        conn = self.postgres_db.pool.getconn()
        
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT id, share_url, status, total_videos, processed_videos,
                           failed_videos, created_at, updated_at, completed_at
                    FROM batch_import_jobs 
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                """, (user_id, limit))
                
                jobs = []
                for row in cursor.fetchall():
                    job_data = {
                        'job_id': row[0],
                        'share_url': row[1],
                        'status': row[2],
                        'total_videos': row[3],
                        'processed_videos': row[4],
                        'failed_videos': row[5],
                        'created_at': row[6].isoformat() if row[6] else None,
                        'updated_at': row[7].isoformat() if row[7] else None,
                        'completed_at': row[8].isoformat() if row[8] else None
                    }
                    jobs.append(job_data)
                
                return jobs
                
        except Exception as e:
            print(f"❌ Error listing batch jobs: {e}")
            return []
        finally:
            self.postgres_db.pool.putconn(conn)
    
    def run_service(self):
        """
        Main background service loop for processing batch jobs
        """
        if not all([self.postgres_db, self.s3_storage]):
            print("❌ Batch import service not properly configured")
            return
        
        print("🚀 Starting batch import background service")
        self.running = True
        
        while self.running:
            try:
                # Get pending jobs
                pending_jobs = self._get_pending_jobs()
                
                if pending_jobs:
                    print(f"📋 Found {len(pending_jobs)} pending batch jobs")
                    
                    for job in pending_jobs:
                        if not self.running:
                            break
                        
                        self._process_batch_job(job['id'])
                
                # Sleep before next poll
                time.sleep(self.poll_interval)
                
            except KeyboardInterrupt:
                print("\n🛑 Batch import service stopping...")
                self.running = False
                break
            except Exception as e:
                print(f"💥 Error in batch service loop: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(30)  # Back off on errors
    
    def _get_pending_jobs(self) -> List[Dict]:
        """Get pending batch jobs from database"""
        conn = self.postgres_db.pool.getconn()
        
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT id, user_id, user_email, share_url
                    FROM batch_import_jobs 
                    WHERE status = 'pending'
                    ORDER BY created_at
                    LIMIT 5
                """)
                
                jobs = []
                for row in cursor.fetchall():
                    jobs.append({
                        'id': row[0],
                        'user_id': row[1],
                        'user_email': row[2],
                        'share_url': row[3]
                    })
                
                return jobs
                
        except Exception as e:
            print(f"❌ Error getting pending jobs: {e}")
            return []
        finally:
            self.postgres_db.pool.putconn(conn)
    
    def _process_batch_job(self, job_id: str):
        """
        Process a single batch job
        
        Args:
            job_id: Batch job ID
        """
        print(f"\n🎯 Processing batch job: {job_id}")
        
        # Mark job as processing
        self._update_job_status(job_id, 'processing', started_at=datetime.now())
        
        try:
            # Get queued videos for this job
            queued_videos = self._get_queued_videos(job_id)
            
            if not queued_videos:
                print(f"   ⚠️  No queued videos found for job {job_id}")
                self._update_job_status(job_id, 'completed')
                return
            
            print(f"   📊 Processing {len(queued_videos)} videos")
            
            processed_count = 0
            failed_count = 0
            
            # Process each video sequentially
            for video in queued_videos:
                if not self.running:
                    break
                
                try:
                    success = self._process_single_video(job_id, video)
                    if success:
                        processed_count += 1
                    else:
                        failed_count += 1
                        
                except Exception as e:
                    print(f"   ❌ Error processing video {video['video_name']}: {e}")
                    failed_count += 1
                    self._update_video_status(
                        video['id'], 
                        'failed', 
                        error_message=str(e),
                        download_completed_at=datetime.now()
                    )
            
            # Update job completion
            total_processed = processed_count + failed_count
            self._update_job_counters(job_id, total_processed, failed_count)
            self._update_job_status(job_id, 'completed', completed_at=datetime.now())
            
            print(f"   ✅ Batch job completed: {processed_count} success, {failed_count} failed")
            
        except Exception as e:
            print(f"   ❌ Batch job failed: {e}")
            import traceback
            traceback.print_exc()
            self._update_job_status(job_id, 'failed', error_message=str(e))
    
    def _get_queued_videos(self, job_id: str) -> List[Dict]:
        """Get queued videos for a batch job"""
        conn = self.postgres_db.pool.getconn()
        
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT id, video_name, video_size, download_url
                    FROM batch_import_videos 
                    WHERE batch_job_id = %s AND status = 'queued'
                    ORDER BY created_at
                """, (job_id,))
                
                videos = []
                for row in cursor.fetchall():
                    videos.append({
                        'id': row[0],
                        'video_name': row[1],
                        'video_size': row[2],
                        'download_url': row[3]
                    })
                
                return videos
                
        except Exception as e:
            print(f"❌ Error getting queued videos: {e}")
            return []
        finally:
            self.postgres_db.pool.putconn(conn)
    
    def _process_single_video(self, job_id: str, video: Dict) -> bool:
        """
        Process a single video from batch job
        
        Args:
            job_id: Batch job ID
            video: Video record dict
            
        Returns:
            True if successful, False otherwise
        """
        video_name = video['video_name']
        video_id = str(uuid.uuid4())
        
        print(f"   📥 Processing: {video_name}")
        
        # Get job details for user info
        job_info = self._get_job_info(job_id)
        if not job_info:
            return False
        
        user_id = job_info['user_id']
        user_email = job_info['user_email']
        share_url = job_info['share_url']
        
        try:
            # Update video status to downloading
            self._update_video_status(
                video['id'], 
                'downloading', 
                progress_percent=0,
                download_started_at=datetime.now()
            )
            
            # Notify via WebSocket
            if self.websocket_manager:
                self._notify_video_progress(user_id, video_name, video_id, 'downloading', 0)
            
            # Download video
            video_data = self._download_video_stream(share_url, video, user_id, video_id, video_name)
            if not video_data:
                return False
            
            # Update to uploading
            self._update_video_status(video['id'], 'uploading', progress_percent=50)
            if self.websocket_manager:
                self._notify_video_progress(user_id, video_name, video_id, 'uploading', 50)
            
            # Upload to S3
            s3_key = self._upload_to_s3(video_data, video_id, video_name)
            if not s3_key:
                return False
            
            # Update to queued
            self._update_video_status(video['id'], 'queued', progress_percent=75)
            if self.websocket_manager:
                self._notify_video_progress(user_id, video_name, video_id, 'queued', 75)
            
            # Create video task
            task_data = self.postgres_db.create_video_task(
                video_id, video_name, user_id, user_email, "in_queue", s3_key=s3_key
            )
            
            # Update video record with video_id and s3_key
            self._update_video_status(
                video['id'], 
                'completed', 
                progress_percent=100,
                video_id=video_id,
                s3_key=s3_key,
                download_completed_at=datetime.now()
            )
            
            # Trigger worker
            if self.trigger_worker_fn:
                self.trigger_worker_fn(
                    video_id=video_id,
                    user_id=user_id,
                    filename=video_name,
                    s3_key=s3_key
                )
            
            # Final notification
            if self.websocket_manager:
                self._notify_video_progress(user_id, video_name, video_id, 'completed', 100)
                self.websocket_manager.notify_task_update(user_id, {
                    'video_id': video_id,
                    'status': 'in_queue',
                    'filename': video_name
                })
            
            print(f"   ✅ Completed: {video_name}")
            return True
            
        except Exception as e:
            print(f"   ❌ Failed: {video_name} - {e}")
            self._update_video_status(
                video['id'], 
                'failed', 
                error_message=str(e),
                download_completed_at=datetime.now()
            )
            if self.websocket_manager:
                self._notify_video_progress(user_id, video_name, video_id, 'failed', 0, str(e))
            return False
    
    def _download_video_stream(self, share_url: str, video: Dict, user_id: str, video_id: str, video_name: str) -> Optional[io.BytesIO]:
        """Download video with streaming and progress updates"""
        try:
            share_token = self.extract_share_token(share_url)
            auth = (share_token, "")
            
            response = self.session.get(
                video['download_url'],
                auth=auth,
                stream=True,
                timeout=300
            )
            response.raise_for_status()
            
            video_data = io.BytesIO()
            downloaded = 0
            total_size = int(response.headers.get('content-length', video['video_size']))
            
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    video_data.write(chunk)
                    downloaded += len(chunk)
                    
                    # Update progress every 5MB
                    if downloaded % (5 * 1024 * 1024) == 0:
                        progress = int((downloaded / total_size) * 50)  # 0-50% for download
                        if self.websocket_manager:
                            self._notify_video_progress(user_id, video_name, video_id, 'downloading', progress)
            
            video_data.seek(0)
            return video_data
            
        except Exception as e:
            print(f"   ❌ Download failed: {e}")
            return None
    
    def _upload_to_s3(self, video_data: io.BytesIO, video_id: str, video_name: str) -> Optional[str]:
        """Upload video data to S3"""
        try:
            file_storage = FileStorage(
                stream=video_data,
                filename=video_name,
                content_type='video/mp4'
            )
            
            s3_key = self.s3_storage.upload_video(file_storage, video_id, video_name)
            return s3_key
            
        except Exception as e:
            print(f"   ❌ S3 upload failed: {e}")
            return None
    
    def _get_job_info(self, job_id: str) -> Optional[Dict]:
        """Get job information"""
        conn = self.postgres_db.pool.getconn()
        
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT user_id, user_email, share_url
                    FROM batch_import_jobs 
                    WHERE id = %s
                """, (job_id,))
                
                row = cursor.fetchone()
                if row:
                    return {
                        'user_id': row[0],
                        'user_email': row[1],
                        'share_url': row[2]
                    }
                return None
                
        except Exception as e:
            print(f"❌ Error getting job info: {e}")
            return None
        finally:
            self.postgres_db.pool.putconn(conn)
    
    def _update_job_status(self, job_id: str, status: str, error_message: str = None, started_at: datetime = None, completed_at: datetime = None):
        """Update batch job status"""
        conn = self.postgres_db.pool.getconn()
        
        try:
            with conn.cursor() as cursor:
                update_fields = ["status = %s"]
                params = [status]
                
                if error_message:
                    update_fields.append("error_message = %s")
                    params.append(error_message)
                
                if started_at:
                    update_fields.append("started_at = %s")
                    params.append(started_at)
                
                if completed_at:
                    update_fields.append("completed_at = %s")
                    params.append(completed_at)
                
                params.append(job_id)
                
                cursor.execute(f"""
                    UPDATE batch_import_jobs 
                    SET {', '.join(update_fields)}
                    WHERE id = %s
                """, params)
                
                conn.commit()
                
        except Exception as e:
            print(f"❌ Error updating job status: {e}")
        finally:
            self.postgres_db.pool.putconn(conn)
    
    def _update_job_counters(self, job_id: str, processed_videos: int, failed_videos: int):
        """Update job processed/failed counters"""
        conn = self.postgres_db.pool.getconn()
        
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE batch_import_jobs 
                    SET processed_videos = %s, failed_videos = %s
                    WHERE id = %s
                """, (processed_videos, failed_videos, job_id))
                
                conn.commit()
                
        except Exception as e:
            print(f"❌ Error updating job counters: {e}")
        finally:
            self.postgres_db.pool.putconn(conn)
    
    def _update_video_status(self, video_record_id: str, status: str, progress_percent: int = None, 
                           error_message: str = None, video_id: str = None, s3_key: str = None,
                           download_started_at: datetime = None, download_completed_at: datetime = None):
        """Update batch import video status"""
        conn = self.postgres_db.pool.getconn()
        
        try:
            with conn.cursor() as cursor:
                update_fields = ["status = %s"]
                params = [status]
                
                if progress_percent is not None:
                    update_fields.append("progress_percent = %s")
                    params.append(progress_percent)
                
                if error_message:
                    update_fields.append("error_message = %s")
                    params.append(error_message)
                
                if video_id:
                    update_fields.append("video_id = %s")
                    params.append(video_id)
                
                if s3_key:
                    update_fields.append("s3_key = %s")
                    params.append(s3_key)
                
                if download_started_at:
                    update_fields.append("download_started_at = %s")
                    params.append(download_started_at)
                
                if download_completed_at:
                    update_fields.append("download_completed_at = %s")
                    params.append(download_completed_at)
                
                params.append(video_record_id)
                
                cursor.execute(f"""
                    UPDATE batch_import_videos 
                    SET {', '.join(update_fields)}
                    WHERE id = %s
                """, params)
                
                conn.commit()
                
        except Exception as e:
            print(f"❌ Error updating video status: {e}")
        finally:
            self.postgres_db.pool.putconn(conn)
    
    def _notify_video_progress(self, user_id: str, video_name: str, video_id: str, status: str, progress: int, error: str = None):
        """Send WebSocket notification for video progress"""
        if self.websocket_manager:
            progress_data = {
                'video_name': video_name,
                'video_id': video_id,
                'status': status,
                'progress_percent': progress
            }
            if error:
                progress_data['error'] = error
            
            self.websocket_manager.notify_batch_import_progress(user_id, progress_data)

