#!/usr/bin/env python3
"""
Email Notification Service for Thakii Backend
Sends email notifications when video processing completes (success/failure)
Uses Brevo (formerly Sendinblue) API for reliable email delivery
Supports multiple recipients and PDF attachments for successful completions
"""

import os
import base64
from typing import List, Optional, Dict, Any
from datetime import datetime
import requests
from pathlib import Path


class EmailService:
    def __init__(self):
        """Initialize Email Service with Brevo API configuration"""
        # Brevo API Configuration
        self.api_key = os.getenv('BREVO_API_KEY', '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')
        self.api_url = 'https://api.brevo.com/v3/smtp/email'
        self.from_email = os.getenv('FROM_EMAIL', 'oudaykhaled@gmail.com')
        self.from_name = os.getenv('FROM_NAME', 'Thakii Lecture2PDF')
        
        # Additional notification recipients (comma-separated)
        additional_emails = os.getenv('NOTIFICATION_EMAILS', '')
        self.additional_recipients = [email.strip() for email in additional_emails.split(',') if email.strip()]
        
        # Validate configuration
        self.is_configured = bool(self.api_key)
        
        if not self.is_configured:
            print("⚠️  Email service not configured. Set BREVO_API_KEY environment variable.")
        else:
            print(f"✅ Email service configured with Brevo API: {self.from_email}")
            if self.additional_recipients:
                print(f"   Additional recipients: {', '.join(self.additional_recipients)}")

    def get_additional_recipients_from_db(self) -> List[str]:
        """Get additional recipients from database configuration"""
        try:
            from core.postgres_db import postgres_db
            import json
            
            recipients_json = postgres_db.get_email_config('additional_recipients')
            if recipients_json:
                return json.loads(recipients_json)
            return []
        except Exception as e:
            print(f"⚠️  Failed to load additional recipients from database: {e}")
            return []

    def update_additional_recipients_in_db(self, recipients: List[str]) -> bool:
        """Update additional recipients in database"""
        try:
            from core.postgres_db import postgres_db
            import json
            
            recipients_json = json.dumps(recipients)
            return postgres_db.set_email_config(
                'additional_recipients', 
                recipients_json, 
                'JSON array of additional email recipients for notifications'
            )
        except Exception as e:
            print(f"❌ Failed to update additional recipients in database: {e}")
            return False

    def send_processing_complete_notification(self, user_email: str, video_id: str, 
                                           filename: str, status: str, 
                                           error_message: Optional[str] = None,
                                           pdf_download_url: Optional[str] = None) -> bool:
        """
        Send email notification when video processing completes using Brevo API
        
        Args:
            user_email: Primary recipient email
            video_id: Video ID
            filename: Original filename
            status: Processing status ('completed' or 'failed')
            error_message: Error message if failed
            pdf_download_url: URL to download PDF if successful
        
        Returns:
            bool: True if email sent successfully
        """
        if not self.is_configured:
            print("❌ Cannot send email: Email service not configured")
            return False
        
        try:
            # Prepare recipients (user + additional recipients from env + database)
            db_recipients = self.get_additional_recipients_from_db()
            all_additional = list(set(self.additional_recipients + db_recipients))  # Remove duplicates
            recipients = [user_email] + all_additional
            
            # Create email data for Brevo API
            email_data = {
                "sender": {
                    "name": self.from_name,
                    "email": self.from_email
                },
                "to": [{"email": email} for email in recipients],
                "subject": self._get_subject(status, filename),
                "htmlContent": self._create_email_body(video_id, filename, status, error_message, pdf_download_url)
            }
            
            # Note: We don't attach PDF, we send a download link in the email body instead
            # This is better for large PDFs and avoids email size limits
            
            # Send email via Brevo API
            return self._send_email_brevo(email_data, recipients)
            
        except Exception as e:
            print(f"❌ Failed to send email notification: {e}")
            return False

    def _get_subject(self, status: str, filename: str) -> str:
        """Generate email subject based on status"""
        if status in ['completed', 'done']:
            return f"✅ PDF Ready: {filename}"
        else:
            return f"❌ Processing Failed: {filename}"

    def _create_email_body(self, video_id: str, filename: str, status: str, 
                          error_message: Optional[str], pdf_url: Optional[str]) -> str:
        """Create HTML email body with presigned download link"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
        
        if status in ['completed', 'done']:
            status_icon = "✅"
            status_text = "Successfully Completed"
            status_color = "#28a745"
            
            # Generate download link via backend endpoint (no presigned URL issues!)
            download_button = ""
            if pdf_url:
                try:
                    # Use backend endpoint for PDF download - this bypasses presigned URL issues
                    backend_url = os.getenv('BACKEND_URL', 'https://thakii-02.fanusdigital.site/thakii-be')
                    download_url = f"{backend_url}/internal/download-pdf/{video_id}"
                    
                    download_button = f"""
                        <p style="text-align: center; margin: 30px 0;">
                            <a href="{download_url}" class="button" style="display: inline-block; background: #28a745; color: white; padding: 15px 30px; text-decoration: none; border-radius: 6px; font-size: 16px; font-weight: bold;">
                                📥 Download PDF
                            </a>
                        </p>
                        <p style="text-align: center; font-size: 14px; color: #666;">
                            Click the button above to download your PDF file.
                        </p>
                    """
                    print(f"✅ Generated download link: {download_url}")
                except Exception as e:
                    print(f"⚠️ Failed to generate download link for email: {e}")
            
            content = f"""
                <p>Great news! Your video has been successfully converted to PDF.</p>
                <p><strong>Click the button below to download your PDF:</strong></p>
                {download_button}
                <p>You can also access it from your dashboard at any time.</p>
            """
        else:
            status_icon = "❌"
            status_text = "Processing Failed"
            status_color = "#dc3545"
            error_details = error_message or "Unknown error occurred"
            content = f"""
                <p>Unfortunately, there was an issue processing your video.</p>
                <p><strong>Error Details:</strong> {error_details}</p>
                <p>Please try uploading your video again, or contact support if the issue persists.</p>
            """
        
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 8px 8px 0 0; text-align: center; }}
                .content {{ background: #f8f9fa; padding: 30px; border-radius: 0 0 8px 8px; }}
                .status {{ background: {status_color}; color: white; padding: 15px; border-radius: 6px; text-align: center; margin: 20px 0; }}
                .details {{ background: white; padding: 20px; border-radius: 6px; border-left: 4px solid {status_color}; }}
                .footer {{ text-align: center; margin-top: 30px; color: #666; font-size: 14px; }}
                .button {{ display: inline-block; background: #667eea; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; margin: 10px 0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>{status_icon} Thakii Lecture2PDF</h1>
                    <p>Video Processing Notification</p>
                </div>
                <div class="content">
                    <div class="status">
                        <h2>{status_text}</h2>
                    </div>
                    
                    {content}
                    
                    <div class="details">
                        <h3>📋 Processing Details</h3>
                        <p><strong>File:</strong> {filename}</p>
                        <p><strong>Video ID:</strong> {video_id}</p>
                        <p><strong>Status:</strong> {status_text}</p>
                        <p><strong>Completed:</strong> {timestamp}</p>
                    </div>
                    
                    <div class="footer">
                        <p>Visit your <a href="https://thakii-02.fanusdigital.site" class="button">Thakii Dashboard</a></p>
                        <p>This is an automated notification from Thakii Lecture2PDF service.</p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """

    def _prepare_pdf_attachment(self, pdf_url: str, filename: str, video_id: str) -> Optional[Dict[str, str]]:
        """Download PDF using presigned URL and prepare attachment data for Brevo API"""
        try:
            print(f"📎 Attempting to prepare PDF attachment for video: {video_id}")
            
            # Import S3Storage to generate presigned URL
            from core.s3_storage import S3Storage
            s3_storage = S3Storage()
            
            # Extract S3 key from the PDF URL
            if 'amazonaws.com/' in pdf_url:
                s3_key = pdf_url.split('amazonaws.com/')[-1]
            else:
                print(f"⚠️  Invalid PDF URL format: {pdf_url}")
                return None
            
            # Generate presigned URL (valid for 72 hours, very long and complex)
            pdf_filename = f"{Path(filename).stem}.pdf"
            presigned_url = s3_storage.generate_presigned_download_url(
                s3_key=s3_key,
                filename=pdf_filename,
                expires_in_hours=72
            )
            
            if not presigned_url:
                print(f"⚠️  Failed to generate presigned URL")
                return None
            
            print(f"📥 Downloading PDF from presigned URL (length: {len(presigned_url)} chars)")
            
            # Download PDF content using presigned URL (no authentication needed!)
            response = requests.get(presigned_url, timeout=60)
            response.raise_for_status()
            pdf_content = response.content
            
            # Encode PDF content to base64 for Brevo API
            pdf_content_b64 = base64.b64encode(pdf_content).decode('utf-8')
            
            attachment = {
                "content": pdf_content_b64,
                "name": pdf_filename
            }
            
            print(f"✅ PDF attachment prepared successfully: {pdf_filename} ({len(pdf_content)} bytes)")
            return attachment
            
        except Exception as e:
            print(f"⚠️  Failed to prepare PDF attachment: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _send_email_brevo(self, email_data: Dict[str, Any], recipients: List[str]) -> bool:
        """Send email via Brevo API"""
        try:
            headers = {
                "api-key": self.api_key,
                "Content-Type": "application/json"
            }
            
            print(f"📧 Sending email via Brevo API to: {', '.join(recipients)}")
            
            response = requests.post(self.api_url, headers=headers, json=email_data, timeout=30)
            
            if response.status_code == 201:
                print(f"✅ Email sent successfully via Brevo API to: {', '.join(recipients)}")
                return True
            else:
                print(f"❌ Brevo API error: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            print(f"❌ Failed to send email via Brevo API: {e}")
            return False

    def send_test_email(self, recipient: str) -> bool:
        """Send test email to verify Brevo API configuration"""
        if not self.is_configured:
            return False
        
        try:
            email_data = {
                "sender": {
                    "name": self.from_name,
                    "email": self.from_email
                },
                "to": [{"email": recipient}],
                "subject": "🧪 Thakii Email Service Test",
                "htmlContent": f"""
                <html>
                <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 8px; text-align: center;">
                            <h2>🧪 Thakii Email Service Test</h2>
                        </div>
                        <div style="background: #f8f9fa; padding: 30px; border-radius: 0 0 8px 8px;">
                            <h3 style="color: #28a745;">✅ Email Service Test Successful</h3>
                            <p>This is a test email from Thakii Lecture2PDF notification service using Brevo API.</p>
                            <p>If you received this email, the email service is configured correctly.</p>
                            <div style="background: white; padding: 15px; border-radius: 6px; border-left: 4px solid #28a745;">
                                <p><strong>Service:</strong> Brevo API</p>
                                <p><strong>Timestamp:</strong> {datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")}</p>
                                <p><strong>From:</strong> {self.from_name} &lt;{self.from_email}&gt;</p>
                            </div>
                        </div>
                    </div>
                </body>
                </html>
                """
            }
            
            return self._send_email_brevo(email_data, [recipient])
            
        except Exception as e:
            print(f"❌ Test email failed: {e}")
            return False


# Global instance
email_service = EmailService()
