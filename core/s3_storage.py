import boto3
import os
import tempfile
from botocore.exceptions import ClientError

class S3Storage:
    def __init__(self):
        self.region = os.getenv('AWS_DEFAULT_REGION', 'us-east-2')
        self.s3_client = boto3.client('s3', region_name=self.region)
        self.bucket_name = os.getenv('S3_BUCKET_NAME', 'thakii-video-storage-1753883631')
    
    def upload_video(self, file_obj, video_id, filename):
        """Upload video file to S3"""
        try:
            # Upload original video
            video_key = f"videos/{video_id}/{filename}"
            self.s3_client.upload_fileobj(file_obj, self.bucket_name, video_key)
            return video_key
        except ClientError as e:
            print(f"Error uploading video to S3: {e}")
            raise
    
    def download_video_to_temp(self, video_id, filename):
        """Download video from S3 to temporary file"""
        try:
            video_key = f"videos/{video_id}/{filename}"
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4')
            self.s3_client.download_fileobj(self.bucket_name, video_key, temp_file)
            temp_file.close()
            return temp_file.name
        except ClientError as e:
            print(f"Error downloading video from S3: {e}")
            raise
    
    def upload_subtitle(self, subtitle_content, video_id):
        """Upload subtitle file to S3"""
        try:
            subtitle_key = f"subtitles/{video_id}.srt"
            self.s3_client.put_object(
                Bucket=self.bucket_name, 
                Key=subtitle_key, 
                Body=subtitle_content
            )
            return subtitle_key
        except ClientError as e:
            print(f"Error uploading subtitle to S3: {e}")
            raise
    
    def download_subtitle_to_temp(self, video_id):
        """Download subtitle from S3 to temporary file"""
        try:
            subtitle_key = f"subtitles/{video_id}.srt"
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.srt', mode='w')
            
            # Download subtitle content
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=subtitle_key)
            subtitle_content = response['Body'].read().decode('utf-8')
            
            temp_file.write(subtitle_content)
            temp_file.close()
            return temp_file.name
        except ClientError as e:
            print(f"Error downloading subtitle from S3: {e}")
            raise
    
    def upload_pdf(self, pdf_path, video_id):
        """Upload generated PDF to S3"""
        try:
            pdf_key = f"pdfs/{video_id}.pdf"
            with open(pdf_path, 'rb') as pdf_file:
                self.s3_client.upload_fileobj(pdf_file, self.bucket_name, pdf_key)
            return pdf_key
        except ClientError as e:
            print(f"Error uploading PDF to S3: {e}")
            raise
    
    def download_pdf(self, video_id, original_filename=None):
        """Get PDF download URL from S3 with correct filename"""
        try:
            # Use correct S3 path structure: pdfs/{video_id}/{video_id}.pdf
            pdf_key = f"pdfs/{video_id}/{video_id}.pdf"
            
            # Determine the download filename
            if original_filename:
                # Remove video extension and add .pdf
                pdf_filename = original_filename.rsplit('.', 1)[0] + '.pdf'
            else:
                pdf_filename = f"{video_id}.pdf"
            
            print(f"🔧 S3 Download: {pdf_key} → filename: {pdf_filename}")
            
            # Generate a presigned URL with Content-Disposition header
            download_url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.bucket_name, 
                    'Key': pdf_key,
                    'ResponseContentDisposition': f'attachment; filename="{pdf_filename}"'
                },
                ExpiresIn=3600  # URL expires in 1 hour
            )
            return download_url
        except ClientError as e:
            print(f"Error generating PDF download URL: {e}")
            raise
    
    def download_file(self, s3_key):
        """Download file content from S3 and return as bytes"""
        try:
            print(f"📥 Downloading file from S3: {s3_key}")
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=s3_key)
            content = response['Body'].read()
            print(f"✅ Downloaded {len(content)} bytes from S3")
            return content
        except ClientError as e:
            print(f"❌ Error downloading file from S3: {e}")
            return None
    
    def generate_presigned_download_url(self, s3_key, filename=None, expires_in_hours=72):
        """
        Generate a presigned URL for downloading a file from S3 without authentication
        
        Args:
            s3_key: S3 object key (path to file)
            filename: Optional custom filename for download
            expires_in_hours: URL expiration time in hours (default: 72 hours)
        
        Returns:
            Long, complex presigned URL that allows temporary unauthenticated access
        """
        try:
            params = {
                'Bucket': self.bucket_name,
                'Key': s3_key
            }
            
            # Add custom filename if provided
            if filename:
                params['ResponseContentDisposition'] = f'attachment; filename="{filename}"'
            
            # Generate presigned URL (expires in specified hours)
            expires_in_seconds = expires_in_hours * 3600  # Convert hours to seconds
            presigned_url = self.s3_client.generate_presigned_url(
                'get_object',
                Params=params,
                ExpiresIn=expires_in_seconds
            )
            
            print(f"✅ Generated presigned URL (expires in {expires_in_hours}h): {s3_key}")
            return presigned_url
            
        except ClientError as e:
            print(f"❌ Error generating presigned URL: {e}")
            return None
    
    def cleanup_temp_files(self, *file_paths):
        """Clean up temporary files"""
        for file_path in file_paths:
            try:
                if file_path and os.path.exists(file_path):
                    os.unlink(file_path)
            except Exception as e:
                print(f"Error cleaning up temp file {file_path}: {e}") 