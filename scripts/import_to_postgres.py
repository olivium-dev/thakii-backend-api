#!/usr/bin/env python3
"""
Import data from JSON files to PostgreSQL
"""

import os
import json
import datetime
from pathlib import Path
import psycopg2
from psycopg2.extras import Json
from dotenv import load_dotenv

load_dotenv()

def parse_datetime(value):
    """Parse ISO datetime string to Python datetime"""
    if not value:
        return None
    try:
        if isinstance(value, str):
            return datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
        return value
    except:
        return None

def import_video_tasks(conn, data):
    """Import video_tasks collection"""
    print(f"\n📹 Importing video_tasks...")
    
    cursor = conn.cursor()
    count = 0
    errors = 0
    
    for task in data:
        try:
            cursor.execute("""
                INSERT INTO video_tasks 
                (video_id, filename, user_id, user_email, status, upload_date,
                 created_at, updated_at, s3_key, pdf_url, error_message,
                 processing_start, processing_end)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (video_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    updated_at = EXCLUDED.updated_at,
                    pdf_url = EXCLUDED.pdf_url,
                    error_message = EXCLUDED.error_message,
                    processing_end = EXCLUDED.processing_end
            """, (
                task.get('video_id'),
                task.get('filename'),
                task.get('user_id'),
                task.get('user_email'),
                task.get('status', 'in_queue'),
                parse_datetime(task.get('upload_date')) or datetime.datetime.now(),
                parse_datetime(task.get('created_at')) or datetime.datetime.now(),
                parse_datetime(task.get('updated_at')) or datetime.datetime.now(),
                task.get('s3_key'),
                task.get('pdf_url'),
                task.get('error_message'),
                parse_datetime(task.get('processing_start')),
                parse_datetime(task.get('processing_end'))
            ))
            count += 1
        except Exception as e:
            print(f"   ❌ Error importing task {task.get('video_id')}: {e}")
            errors += 1
    
    conn.commit()
    print(f"   ✅ Imported {count} video tasks ({errors} errors)")
    return count, errors

def import_admin_users(conn, data):
    """Import admin_users collection"""
    print(f"\n👑 Importing admin_users...")
    
    cursor = conn.cursor()
    count = 0
    errors = 0
    
    for admin in data:
        try:
            cursor.execute("""
                INSERT INTO admin_users 
                (email, role, status, is_super_admin, description, added_by,
                 created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (email) DO UPDATE SET
                    role = EXCLUDED.role,
                    status = EXCLUDED.status,
                    updated_at = EXCLUDED.updated_at
            """, (
                admin.get('email'),
                admin.get('role', 'admin'),
                admin.get('status', 'active'),
                admin.get('is_super_admin', False),
                admin.get('description'),
                admin.get('added_by', 'system'),
                parse_datetime(admin.get('created_at')) or datetime.datetime.now(),
                parse_datetime(admin.get('updated_at')) or datetime.datetime.now()
            ))
            count += 1
        except Exception as e:
            print(f"   ❌ Error importing admin {admin.get('email')}: {e}")
            errors += 1
    
    conn.commit()
    print(f"   ✅ Imported {count} admin users ({errors} errors)")
    return count, errors

def import_processing_servers(conn, data):
    """Import processing_servers collection"""
    print(f"\n🖥️  Importing processing_servers...")
    
    cursor = conn.cursor()
    count = 0
    errors = 0
    
    for server in data:
        try:
            cursor.execute("""
                INSERT INTO processing_servers 
                (name, url, type, status, description, health_status,
                 created_at, updated_at, last_health_check)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (name) DO UPDATE SET
                    url = EXCLUDED.url,
                    status = EXCLUDED.status,
                    health_status = EXCLUDED.health_status,
                    updated_at = EXCLUDED.updated_at
            """, (
                server.get('name'),
                server.get('url'),
                server.get('type', 'processing'),
                server.get('status', 'active'),
                server.get('description'),
                Json(server.get('health_status', {})),
                parse_datetime(server.get('created_at')) or datetime.datetime.now(),
                parse_datetime(server.get('updated_at')) or datetime.datetime.now(),
                parse_datetime(server.get('last_health_check'))
            ))
            count += 1
        except Exception as e:
            print(f"   ❌ Error importing server {server.get('name')}: {e}")
            errors += 1
    
    conn.commit()
    print(f"   ✅ Imported {count} processing servers ({errors} errors)")
    return count, errors

def import_notifications(conn, data):
    """Import notifications collection"""
    print(f"\n🔔 Importing notifications...")
    
    cursor = conn.cursor()
    count = 0
    errors = 0
    
    for notification in data:
        try:
            cursor.execute("""
                INSERT INTO notifications 
                (user_id, title, body, data, type, read, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                notification.get('user_id'),
                notification.get('title'),
                notification.get('body'),
                Json(notification.get('data', {})),
                notification.get('type', 'push_notification'),
                notification.get('read', False),
                parse_datetime(notification.get('created_at')) or datetime.datetime.now()
            ))
            count += 1
        except Exception as e:
            print(f"   ❌ Error importing notification: {e}")
            errors += 1
    
    conn.commit()
    print(f"   ✅ Imported {count} notifications ({errors} errors)")
    return count, errors

def main():
    """Main import function"""
    print("=" * 60)
    print("PostgreSQL Data Import from Firestore Export")
    print("=" * 60)
    
    # Connect to PostgreSQL
    try:
        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            port=os.getenv('POSTGRES_PORT', '5432'),
            database=os.getenv('POSTGRES_DB', 'thakii_production'),
            user=os.getenv('POSTGRES_USER', 'thakii_user'),
            password=os.getenv('POSTGRES_PASSWORD')
        )
        print("✅ Connected to PostgreSQL")
    except Exception as e:
        print(f"❌ Failed to connect to PostgreSQL: {e}")
        return
    
    # Find export directory
    export_dir = Path(__file__).parent / 'exports'
    
    if not export_dir.exists():
        print(f"❌ Export directory not found: {export_dir}")
        print("   Run scripts/export_firestore_data.py first")
        return
    
    print(f"\n📁 Import directory: {export_dir}")
    
    # Load and import each collection
    results = {}
    
    # Import video_tasks
    video_tasks_file = export_dir / 'video_tasks.json'
    if video_tasks_file.exists():
        with open(video_tasks_file, 'r') as f:
            data = json.load(f)
        count, errors = import_video_tasks(conn, data)
        results['video_tasks'] = {'imported': count, 'errors': errors}
    else:
        print(f"\n⚠️  Skipping video_tasks (file not found)")
        results['video_tasks'] = {'imported': 0, 'errors': 0}
    
    # Import admin_users
    admin_users_file = export_dir / 'admin_users.json'
    if admin_users_file.exists():
        with open(admin_users_file, 'r') as f:
            data = json.load(f)
        count, errors = import_admin_users(conn, data)
        results['admin_users'] = {'imported': count, 'errors': errors}
    else:
        print(f"\n⚠️  Skipping admin_users (file not found)")
        results['admin_users'] = {'imported': 0, 'errors': 0}
    
    # Import processing_servers
    servers_file = export_dir / 'processing_servers.json'
    if servers_file.exists():
        with open(servers_file, 'r') as f:
            data = json.load(f)
        count, errors = import_processing_servers(conn, data)
        results['processing_servers'] = {'imported': count, 'errors': errors}
    else:
        print(f"\n⚠️  Skipping processing_servers (file not found)")
        results['processing_servers'] = {'imported': 0, 'errors': 0}
    
    # Import notifications
    notifications_file = export_dir / 'notifications.json'
    if notifications_file.exists():
        with open(notifications_file, 'r') as f:
            data = json.load(f)
        count, errors = import_notifications(conn, data)
        results['notifications'] = {'imported': count, 'errors': errors}
    else:
        print(f"\n⚠️  Skipping notifications (file not found)")
        results['notifications'] = {'imported': 0, 'errors': 0}
    
    # Close connection
    conn.close()
    
    # Print summary
    print("\n" + "=" * 60)
    print("IMPORT SUMMARY")
    print("=" * 60)
    
    total_imported = 0
    total_errors = 0
    
    for collection, stats in results.items():
        imported = stats['imported']
        errors = stats['errors']
        total_imported += imported
        total_errors += errors
        print(f"   {collection}: {imported} imported, {errors} errors")
    
    print(f"\n   TOTAL: {total_imported} records imported")
    if total_errors > 0:
        print(f"   ⚠️  {total_errors} errors occurred during import")
    
    print("\n✅ Import completed!")
    
    # Verify data
    print("\n📊 Verification:")
    conn = psycopg2.connect(
        host=os.getenv('POSTGRES_HOST', 'localhost'),
        port=os.getenv('POSTGRES_PORT', '5432'),
        database=os.getenv('POSTGRES_DB', 'thakii_production'),
        user=os.getenv('POSTGRES_USER', 'thakii_user'),
        password=os.getenv('POSTGRES_PASSWORD')
    )
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM video_tasks")
    print(f"   Video tasks in PostgreSQL: {cursor.fetchone()[0]}")
    
    cursor.execute("SELECT COUNT(*) FROM admin_users")
    print(f"   Admin users in PostgreSQL: {cursor.fetchone()[0]}")
    
    cursor.execute("SELECT COUNT(*) FROM processing_servers")
    print(f"   Processing servers in PostgreSQL: {cursor.fetchone()[0]}")
    
    cursor.execute("SELECT COUNT(*) FROM notifications")
    print(f"   Notifications in PostgreSQL: {cursor.fetchone()[0]}")
    
    conn.close()
    
    print("\n📋 Next steps:")
    print("   1. Verify the data in PostgreSQL")
    print("   2. Test the application with PostgreSQL")
    print("   3. Keep Firestore credentials for rollback if needed")

if __name__ == '__main__':
    main()

