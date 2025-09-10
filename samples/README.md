# Sample Videos for Testing

This directory contains sample video files for testing the Thakii Backend API and worker integration.

## Files

### `quick_test_video.mp4`
- **Size**: ~513 KB
- **Purpose**: Quick testing of video upload and processing pipeline
- **Usage**: Test file for API endpoints and worker integration

## Usage Examples

### Test Video Upload
```bash
# Upload sample video using curl
curl -X POST \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@samples/quick_test_video.mp4" \
  https://thakii-02.fanusdigital.site/upload

# Or using mock token for testing
curl -X POST \
  -H "Authorization: Bearer thakii-mock-prod-token" \
  -F "file=@samples/quick_test_video.mp4" \
  https://thakii-02.fanusdigital.site/upload
```

### Test Local Worker Trigger
```bash
# Test local worker processing (development mode)
python3 trigger_worker_clean.py VIDEO_ID
```

### Monitor Processing Status
```bash
# Check video processing status
curl -H "Authorization: Bearer YOUR_TOKEN" \
  https://thakii-02.fanusdigital.site/admin/videos
```

## Integration Testing

These sample files are used for:
- ✅ **API Upload Testing** - Verify file upload functionality
- ✅ **Worker Integration** - Test backend → worker communication
- ✅ **Pipeline Validation** - End-to-end processing verification
- ✅ **Development Testing** - Local worker script validation

## File Management

- **Keep files small** - For quick testing and CI/CD
- **Update .gitignore** if adding large files
- **Document new samples** in this README
