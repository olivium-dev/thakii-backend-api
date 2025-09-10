#!/usr/bin/env python3
"""
Thakii Backend API - Local Worker Trigger (Development/Testing Only)

This script is for LOCAL DEVELOPMENT AND TESTING purposes only.
In production, the backend API communicates with the separate worker service:
https://github.com/olivium-dev/thakii-worker-service.git

This local trigger allows testing the video processing pipeline without
setting up the full distributed worker service.
"""

import sys
import os
import subprocess
import tempfile
import argparse
from dotenv import load_dotenv

# Add the parent directory to Python path so we can import from core
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.s3_storage import S3Storage
from core.firestore_db import firestore_db


def process_video(video_id: str, lecture2pdf_path: str) -> bool:
    load_dotenv()
    s3_storage = S3Storage()

    python_exec = sys.executable or "python3"

    temp_video_path = None
    temp_srt_path = None
    temp_pdf_path = None

    try:
        # Get task details
        task = firestore_db.get_video_task(video_id)
        if not task:
            print(f"Task not found: {video_id}")
            return False

        firestore_db.update_video_task(video_id, {
            'status': 'processing',
            'started_at': firestore_db.get_timestamp()
        })

        # Download source video
        temp_video_path = s3_storage.download_video_to_temp(video_id, task['filename'])

        # Generate subtitles
        temp_srt_file = tempfile.NamedTemporaryFile(delete=False, suffix='.srt')
        temp_srt_path = temp_srt_file.name
        temp_srt_file.close()

        subprocess.run([
            python_exec,
            os.path.join(lecture2pdf_path, 'src', 'subtitle_generator.py'),
            temp_video_path,
            temp_srt_path
        ], check=True)

        # Generate PDF
        temp_pdf_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
        temp_pdf_path = temp_pdf_file.name
        temp_pdf_file.close()

        subprocess.run([
            python_exec,
            os.path.join(lecture2pdf_path, 'src', 'main.py'),
            temp_video_path,
            temp_srt_path,
            temp_pdf_path
        ], check=True)

        # Upload outputs
        pdf_url = s3_storage.upload_pdf(temp_pdf_path, video_id)
        subtitle_url = s3_storage.upload_subtitle(temp_srt_path, video_id)

        firestore_db.update_video_task(video_id, {
            'status': 'completed',
            'completed_at': firestore_db.get_timestamp(),
            'pdf_url': pdf_url,
            'subtitle_url': subtitle_url
        })

        print(f"Processed successfully: {video_id}")
        return True

    except Exception as error:
        print(f"Worker error for {video_id}: {error}")
        try:
            firestore_db.update_video_task(video_id, {
                'status': 'failed',
                'failed_at': firestore_db.get_timestamp(),
                'error_message': str(error)
            })
        except Exception as update_error:
            print(f"Failed to update task status: {update_error}")
        return False
    finally:
        for path in (temp_video_path, temp_srt_path, temp_pdf_path):
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except Exception:
                    pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('video_id')
    parser.add_argument('--lecture2pdf-path', default=os.getenv('LECTURE2PDF_PATH', '/home/ec2-user/thakii-backend-api/lecture2pdf-external'))
    args = parser.parse_args()

    ok = process_video(args.video_id, args.lecture2pdf_path)
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())


