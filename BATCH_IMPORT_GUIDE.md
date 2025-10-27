# Batch Video Import Feature - Implementation Guide

## Overview

The Batch Video Import feature allows users to import multiple videos directly from wolkesicher.de (Nextcloud) public shares. The backend downloads videos directly from the share and uploads them to S3, bypassing client-side download/upload.

## Architecture

### Flow

1. **User enters share URL** → Frontend validates and sends to backend
2. **Backend lists videos** → WebDAV PROPFIND request to fetch video metadata
3. **User selects videos** → All videos selected by default, user can uncheck
4. **Backend imports videos** → For each selected video:
   - Download from WebDAV
   - Stream directly to S3
   - Create database task
   - Trigger worker processing
   - Send WebSocket progress updates

### Components

#### Backend

**`core/batch_import_service.py`**
- `BatchImportService` class handles all WebDAV operations
- `list_videos_from_share(share_url)` - Lists all video files from a share
- `download_and_import_video(...)` - Downloads and imports a single video
- Uses streaming to avoid disk space issues
- Sends real-time WebSocket progress updates

**`app.py`** - Two new endpoints:
- `POST /batch-import/list-videos` - Lists videos from a share URL
- `POST /batch-import/import-videos` - Imports selected videos

**`core/websocket_manager.py`**
- `notify_batch_import_progress(user_id, progress_data)` - Sends per-video progress

#### Frontend

**`src/components/BatchImportModal.jsx`**
- 4-step modal UI:
  1. URL input
  2. Loading spinner
  3. Video selection (checkboxes, all selected by default)
  4. Import progress (per-video status)
- Listens to `batch_import_progress` WebSocket events
- Shows real-time progress for each video

**`src/components/FileUpload.jsx`**
- Added "Batch Import" button next to "Browse Files"
- Integrates `BatchImportModal` component

**`src/services/api.js`**
- `listBatchImportVideos(shareUrl)` - API call to list videos
- `importBatchVideos(shareUrl, selectedVideos)` - API call to import videos

## API Documentation

### List Videos

**Endpoint:** `POST /batch-import/list-videos`

**Authentication:** Required (Firebase token)

**Request Body:**
```json
{
  "share_url": "https://fanusdigital.wolkesicher.de/s/TOKEN"
}
```

**Response:**
```json
{
  "videos": [
    {
      "name": "video1.mp4",
      "size": 1048576,
      "type": "video/mp4",
      "is_video": true,
      "download_url": "https://..."
    }
  ],
  "total_count": 1,
  "total_size": 1048576
}
```

### Import Videos

**Endpoint:** `POST /batch-import/import-videos`

**Authentication:** Required (Firebase token)

**Request Body:**
```json
{
  "share_url": "https://fanusdigital.wolkesicher.de/s/TOKEN",
  "selected_videos": [
    {
      "name": "video1.mp4",
      "size": 1048576,
      "download_url": "https://...",
      "type": "video/mp4"
    }
  ]
}
```

**Response:**
```json
{
  "batch_id": "uuid",
  "total_count": 1,
  "success_count": 1,
  "failed_count": 0,
  "imported_videos": [
    {
      "video_id": "uuid",
      "video_name": "video1.mp4",
      "status": "success",
      "s3_key": "videos/uuid/video1.mp4"
    }
  ],
  "failed_videos": []
}
```

## WebSocket Events

### `batch_import_progress`

Sent during video import to provide real-time progress updates.

**Event Data:**
```json
{
  "video_name": "video1.mp4",
  "video_id": "uuid",
  "status": "downloading|uploading|queued|completed|failed",
  "progress_percent": 0-100,
  "error": "Error message (optional, only for failed status)"
}
```

**Status Flow:**
- `downloading` (0-50%) - Downloading from wolkesicher.de
- `uploading` (50-75%) - Uploading to S3
- `queued` (75-100%) - Task created, worker notified
- `completed` (100%) - Import successful
- `failed` (0%) - Import failed with error message

## Supported Video Formats

- `.mp4`, `.avi`, `.mkv`, `.mov`, `.wmv`, `.flv`
- `.webm`, `.m4v`, `.3gp`, `.ogv`, `.m2ts`, `.ts`

## WebDAV Authentication

Nextcloud public shares use a special authentication:
- **Username:** Share token (extracted from `/s/TOKEN` in URL)
- **Password:** Empty string

## Error Handling

- **Invalid URL:** Returns error if share token cannot be extracted
- **WebDAV failure:** Returns error with HTTP status code
- **Download failure:** Marked as failed, continues with other videos
- **Upload failure:** Marked as failed, continues with other videos
- **Worker trigger failure:** Logged but doesn't fail the import

## Testing

### Manual Testing Steps

1. **Backend - List Videos:**
```bash
curl -X POST https://thakii-02.fanusdigital.site/thakii-be/batch-import/list-videos \
  -H "Authorization: Bearer YOUR_FIREBASE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"share_url": "https://fanusdigital.wolkesicher.de/s/SHARE_TOKEN"}'
```

2. **Backend - Import Videos:**
```bash
curl -X POST https://thakii-02.fanusdigital.site/thakii-be/batch-import/import-videos \
  -H "Authorization: Bearer YOUR_FIREBASE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "share_url": "https://fanusdigital.wolkesicher.de/s/SHARE_TOKEN",
    "selected_videos": [
      {
        "name": "test.mp4",
        "size": 1048576,
        "download_url": "https://...",
        "type": "video/mp4"
      }
    ]
  }'
```

3. **Frontend - Full Flow:**
   - Open frontend at `https://thakii-02.fanusdigital.site`
   - Log in with Firebase
   - Click "Batch Import" button
   - Enter share URL: `https://fanusdigital.wolkesicher.de/s/SHARE_TOKEN`
   - Click "Fetch Videos"
   - Select/deselect videos
   - Click "Import X Videos"
   - Observe real-time progress for each video
   - Verify videos appear in main list after import

### Testing Checklist

- [ ] Backend can list videos from wolkesicher.de share
- [ ] Backend downloads and uploads to S3 without storing locally
- [ ] Frontend modal shows video list with checkboxes
- [ ] All videos selected by default
- [ ] Import shows per-video progress
- [ ] WebSocket updates work for each video
- [ ] Failed videos don't block others
- [ ] Videos appear in main video list after import
- [ ] Email notifications sent after video processing completes
- [ ] Worker processes imported videos correctly

## Deployment

### Backend Deployment

1. Upload new files to server:
```bash
scp thakii-backend-api/core/batch_import_service.py thakii-02:/root/thakii-backend-api/core/
scp thakii-backend-api/core/websocket_manager.py thakii-02:/root/thakii-backend-api/core/
scp thakii-backend-api/app.py thakii-02:/root/thakii-backend-api/
```

2. Restart backend:
```bash
ssh thakii-02
cd /root/thakii-backend-api
source venv/bin/activate
pkill -f "python app.py"
python app.py &
```

### Frontend Deployment

1. Build frontend:
```bash
cd thakii-frontend
npm run build
```

2. Upload to server:
```bash
scp -r dist/* thakii-02:/var/www/thakii-frontend/
```

## Future Enhancements

- YouTube import support
- Google Drive import support
- Batch status page (view all ongoing imports)
- Import history
- Scheduled imports
- Import from private shares (with credentials)
- Retry failed imports
- Cancel ongoing imports

## Troubleshooting

### "Failed to list videos" Error

**Cause:** Invalid share URL or WebDAV connection failure

**Solution:**
1. Verify share URL format: `https://domain.wolkesicher.de/s/TOKEN`
2. Check if share is public (no password)
3. Test share URL in browser
4. Check backend logs for WebDAV response

### Videos stuck in "downloading" status

**Cause:** Network timeout or large file size

**Solution:**
1. Check network connectivity between backend and wolkesicher.de
2. Increase timeout in `batch_import_service.py` (default: 300s)
3. Check backend disk space

### WebSocket progress not updating

**Cause:** WebSocket not connected or user not in room

**Solution:**
1. Check browser console for WebSocket connection
2. Verify user is authenticated
3. Check backend logs for WebSocket emit calls
4. Ensure frontend is listening to `batch_import_progress` event

## Related Documentation

- [Email Notifications Guide](EMAIL_NOTIFICATIONS_GUIDE.md)
- [WebSocket Architecture](WEBSOCKET_FINAL_SOLUTION.md)
- [Worker Service Documentation](../thakii-worker-service/README.md)

