#!/usr/bin/env python3
"""
Batch Import Service for wolkesicher.de (Nextcloud) shares
Downloads videos directly from WebDAV shares and imports them into the system
"""

import requests
import xml.etree.ElementTree as ET
import re
import uuid
import io
from pathlib import Path
from urllib.parse import urlparse, unquote
from typing import List, Dict, Optional
from werkzeug.datastructures import FileStorage


class BatchImportService:
    """Service for importing videos from wolkesicher.de Nextcloud shares"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Thakii-BatchImport/1.0'
        })
    
    def extract_base_url(self, url: str) -> str:
        """Extract base URL from share URL"""
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"
    
    def extract_share_token(self, url: str) -> str:
        """Extract share token from URL (format: /s/TOKEN)"""
        match = re.search(r'/s/([^/]+)', url)
        if match:
            return match.group(1)
        raise ValueError(f"Could not extract share token from URL: {url}")
    
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
            webdav_url = f"{base_url}/public.php/webdav/"
            
            print(f"   Base URL: {base_url}")
            print(f"   Share Token: {share_token}")
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

