#!/usr/bin/env python3
"""
Export data from Firestore to JSON files for migration to PostgreSQL
"""

import os
import json
import datetime
from pathlib import Path
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

load_dotenv()

def serialize_value(value):
    """Convert Firestore values to JSON-serializable format"""
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    elif isinstance(value, dict):
        return {k: serialize_value(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [serialize_value(item) for item in value]
    else:
        return value

def export_collection(db, collection_name, output_file):
    """Export a Firestore collection to JSON file"""
    print(f"\n📦 Exporting collection: {collection_name}")
    
    try:
        collection_ref = db.collection(collection_name)
        docs = collection_ref.stream()
        
        data = []
        count = 0
        
        for doc in docs:
            doc_data = doc.to_dict()
            doc_data['id'] = doc.id  # Add document ID
            
            # Serialize all values
            doc_data = serialize_value(doc_data)
            
            data.append(doc_data)
            count += 1
        
        # Write to JSON file
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        
        print(f"✅ Exported {count} documents to {output_file}")
        return count
        
    except Exception as e:
        print(f"❌ Error exporting {collection_name}: {e}")
        return 0

def main():
    """Main export function"""
    print("=" * 60)
    print("Firestore Data Export for PostgreSQL Migration")
    print("=" * 60)
    
    # Initialize Firebase Admin SDK
    try:
        # Check if already initialized
        try:
            firebase_admin.get_app()
            print("✅ Firebase Admin SDK already initialized")
            db = firestore.client()
        except ValueError:
            # Initialize Firebase
            cred_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS') or os.getenv('FIREBASE_SERVICE_ACCOUNT_KEY')
            if not cred_path:
                print("❌ Firebase credentials not found")
                print("   Set GOOGLE_APPLICATION_CREDENTIALS or FIREBASE_SERVICE_ACCOUNT_KEY")
                return
            
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
            print("✅ Firebase Admin SDK initialized")
            db = firestore.client()
        
    except Exception as e:
        print(f"❌ Failed to initialize Firebase: {e}")
        return
    
    # Create export directory
    export_dir = Path(__file__).parent / 'exports'
    export_dir.mkdir(exist_ok=True)
    print(f"\n📁 Export directory: {export_dir}")
    
    # Collections to export
    collections = {
        'video_tasks': 'video_tasks.json',
        'admin_users': 'admin_users.json',
        'processing_servers': 'processing_servers.json',
        'notifications': 'notifications.json'
    }
    
    # Export each collection
    total_docs = 0
    results = {}
    
    for collection_name, output_file in collections.items():
        output_path = export_dir / output_file
        count = export_collection(db, collection_name, output_path)
        results[collection_name] = count
        total_docs += count
    
    # Create summary
    print("\n" + "=" * 60)
    print("EXPORT SUMMARY")
    print("=" * 60)
    
    for collection_name, count in results.items():
        print(f"   {collection_name}: {count} documents")
    
    print(f"\n   TOTAL: {total_docs} documents exported")
    
    # Save metadata
    metadata = {
        'export_date': datetime.datetime.now().isoformat(),
        'total_documents': total_docs,
        'collections': results
    }
    
    metadata_file = export_dir / 'export_metadata.json'
    with open(metadata_file, 'w') as f:
        json.dump(metadata, f, indent=2)
    
    print(f"\n📊 Metadata saved to {metadata_file}")
    print("\n✅ Export completed successfully!")
    print(f"   All files saved in: {export_dir}")
    
    print("\n📋 Next steps:")
    print("   1. Review the exported JSON files")
    print("   2. Run scripts/import_to_postgres.py to import data")

if __name__ == '__main__':
    main()

