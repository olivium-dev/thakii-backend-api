import boto3
import os
import tempfile
from botocore.exceptions import ClientError

class S3Storage:
    def __init__(self):
        self.s3_client = boto3.client('s3')
        self.bucket_name = os.getenv('S3_BUCKET_NAME', 'thakii-video-storage-1753883631')
        self.region = os.getenv('AWS_DEFAULT_REGION', 'us-east-2')
    
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
    
    def download_pdf(self, video_id):
        """Get PDF download URL from S3"""
        try:
            pdf_key = f"pdfs/{video_id}/{video_id}.pdf"
            # Generate a presigned URL for downloading
            download_url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': pdf_key},
                ExpiresIn=3600  # URL expires in 1 hour
            )
            return download_url
        except ClientError as e:
            print(f"Error generating PDF download URL: {e}")
            raise
    
    def cleanup_temp_files(self, *file_paths):
        """Clean up temporary files"""
        for file_path in file_paths:
            try:
                if file_path and os.path.exists(file_path):
                    os.unlink(file_path)
            except Exception as e:
                print(f"Error cleaning up temp file {file_path}: {e}") 