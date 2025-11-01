#!/usr/bin/env python3
"""
Test script for Email Service functionality
Run this to test email configuration and sending
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add the current directory to Python path to import modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.email_service import email_service

def test_email_configuration():
    """Test email service configuration"""
    print("🧪 Testing Email Service Configuration")
    print("=" * 50)
    
    print(f"Service Type: Brevo API")
    print(f"API URL: {email_service.api_url}")
    print(f"From Email: {email_service.from_email}")
    print(f"From Name: {email_service.from_name}")
    print(f"Configured: {email_service.is_configured}")
    print(f"API Key: {email_service.api_key[:20]}..." if email_service.api_key else "Not set")
    print(f"Additional Recipients: {email_service.additional_recipients}")
    
    if not email_service.is_configured:
        print("\n❌ Email service is not configured!")
        print("Please set BREVO_API_KEY environment variable.")
        return False
    
    print("\n✅ Email service configuration looks good!")
    return True

def test_send_email():
    """Test sending an email"""
    if not email_service.is_configured:
        print("❌ Cannot test email sending - service not configured")
        return False
    
    # Get recipient email
    recipient = input("\nEnter recipient email for test: ").strip()
    if not recipient:
        print("❌ No recipient provided")
        return False
    
    print(f"\n📧 Sending test email to {recipient}...")
    
    # Send test email
    success = email_service.send_test_email(recipient)
    
    if success:
        print(f"✅ Test email sent successfully to {recipient}")
        return True
    else:
        print(f"❌ Failed to send test email to {recipient}")
        return False

def test_notification_email():
    """Test sending a processing notification email"""
    if not email_service.is_configured:
        print("❌ Cannot test notification email - service not configured")
        return False
    
    # Get recipient email
    recipient = input("\nEnter recipient email for notification test: ").strip()
    if not recipient:
        print("❌ No recipient provided")
        return False
    
    # Test success notification
    print(f"\n📧 Sending SUCCESS notification email to {recipient}...")
    success = email_service.send_processing_complete_notification(
        user_email=recipient,
        video_id="test-video-123",
        filename="test-video.mp4",
        status="completed",
        pdf_download_url="https://example.com/test.pdf"
    )
    
    if success:
        print("✅ Success notification sent!")
    else:
        print("❌ Failed to send success notification")
    
    # Test failure notification
    print(f"\n📧 Sending FAILURE notification email to {recipient}...")
    success = email_service.send_processing_complete_notification(
        user_email=recipient,
        video_id="test-video-456",
        filename="test-video-2.mp4",
        status="failed",
        error_message="Test error: Video format not supported"
    )
    
    if success:
        print("✅ Failure notification sent!")
        return True
    else:
        print("❌ Failed to send failure notification")
        return False

def main():
    """Main test function"""
    print("🧪 Thakii Email Service Test Suite")
    print("=" * 50)
    
    # Test 1: Configuration
    if not test_email_configuration():
        return
    
    # Ask user what to test
    print("\nWhat would you like to test?")
    print("1. Send simple test email")
    print("2. Send notification emails (success + failure)")
    print("3. Both")
    print("0. Exit")
    
    choice = input("\nEnter your choice (0-3): ").strip()
    
    if choice == "0":
        print("👋 Goodbye!")
        return
    elif choice == "1":
        test_send_email()
    elif choice == "2":
        test_notification_email()
    elif choice == "3":
        test_send_email()
        test_notification_email()
    else:
        print("❌ Invalid choice")
        return
    
    print("\n🎉 Email testing complete!")
    print("\nIf emails were sent successfully, check the recipient's inbox.")
    print("Note: Check spam/junk folder if emails don't appear in inbox.")

if __name__ == "__main__":
    main()
