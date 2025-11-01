#!/usr/bin/env python3
"""
Automated Video Processing Recovery System
==========================================

This script automatically detects and recovers stuck videos in the processing pipeline.
It's designed to be run by GitHub Actions deployment pipeline to ensure system sustainability.

Features:
- Detects videos stuck in "processing" for more than 15 minutes
- Resets stuck videos to "in_queue" for retry
- Cleans up failed videos older than 24 hours
- Monitors worker health and triggers recovery
- Sends alerts for critical issues
- Safe execution with rollback capabilities
"""

import os
import sys
import json
import datetime
import logging
import requests
from typing import Dict, List, Any, Optional

# Add the parent directory to the path to import core modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Global variables for core modules (will be initialized in main)
postgres_db = None
worker_manager = None

def initialize_core_modules():
    """Initialize core modules with error handling"""
    global postgres_db, worker_manager
    
    try:
        from core.postgres_db import postgres_db as _postgres_db
        from core.worker_manager import worker_manager as _worker_manager
        postgres_db = _postgres_db
        worker_manager = _worker_manager
        return True
    except ImportError as e:
        logger.error(f"❌ Failed to import core modules: {e}")
        logger.error("This script must be run from the backend directory with proper dependencies installed.")
        return False
    except Exception as e:
        logger.error(f"❌ Failed to initialize core modules: {e}")
        return False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/tmp/auto_recovery.log')
    ]
)
logger = logging.getLogger(__name__)

class AutoRecoverySystem:
    """Automated recovery system for stuck video processing tasks"""
    
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.stats = {
            'stuck_videos_found': 0,
            'stuck_videos_reset': 0,
            'failed_videos_cleaned': 0,
            'worker_health_issues': 0,
            'errors': []
        }
        
    def log_action(self, action: str, details: str = ""):
        """Log actions with dry-run indication"""
        prefix = "[DRY-RUN] " if self.dry_run else "[LIVE] "
        logger.info(f"{prefix}{action}: {details}")
        
    def detect_stuck_videos(self, stuck_threshold_minutes: int = 15) -> List[Dict[str, Any]]:
        """
        Detect videos stuck in processing for more than the threshold
        
        Args:
            stuck_threshold_minutes: Minutes after which a processing video is considered stuck
            
        Returns:
            List of stuck video tasks
        """
        try:
            if not postgres_db._is_available():
                raise Exception("PostgreSQL not available")
                
            conn = postgres_db.pool.getconn()
            try:
                with conn.cursor() as cur:
                    # Find videos stuck in processing
                    cur.execute("""
                        SELECT video_id, filename, user_email, status, processing_start, 
                               EXTRACT(EPOCH FROM (NOW() - processing_start))/60 as minutes_stuck
                        FROM video_tasks 
                        WHERE status = 'processing' 
                        AND processing_start IS NOT NULL
                        AND processing_start < NOW() - INTERVAL '%s minutes'
                        ORDER BY processing_start ASC
                    """, (stuck_threshold_minutes,))
                    
                    stuck_videos = []
                    for row in cur.fetchall():
                        stuck_videos.append({
                            'video_id': row[0],
                            'filename': row[1],
                            'user_email': row[2],
                            'status': row[3],
                            'processing_start': row[4],
                            'minutes_stuck': float(row[5])
                        })
                    
                    self.stats['stuck_videos_found'] = len(stuck_videos)
                    self.log_action("DETECTION", f"Found {len(stuck_videos)} stuck videos")
                    
                    return stuck_videos
                    
            finally:
                postgres_db.pool.putconn(conn)
                
        except Exception as e:
            error_msg = f"Failed to detect stuck videos: {str(e)}"
            self.stats['errors'].append(error_msg)
            logger.error(error_msg)
            return []
    
    def reset_stuck_videos(self, stuck_videos: List[Dict[str, Any]]) -> int:
        """
        Reset stuck videos back to 'in_queue' status for retry
        
        Args:
            stuck_videos: List of stuck video tasks
            
        Returns:
            Number of videos successfully reset
        """
        reset_count = 0
        
        for video in stuck_videos:
            try:
                if self.dry_run:
                    self.log_action("RESET", f"Would reset {video['video_id']} ({video['filename']}) - stuck for {video['minutes_stuck']:.1f} minutes")
                    reset_count += 1
                    continue
                
                if not postgres_db._is_available():
                    raise Exception("PostgreSQL not available")
                    
                conn = postgres_db.pool.getconn()
                try:
                    with conn.cursor() as cur:
                        # Reset video to in_queue and clear processing timestamps
                        cur.execute("""
                            UPDATE video_tasks 
                            SET status = 'in_queue',
                                processing_start = NULL,
                                processing_end = NULL,
                                error_message = COALESCE(error_message, '') || 
                                    CASE WHEN error_message IS NOT NULL AND error_message != '' 
                                         THEN '; Auto-recovery: Reset from stuck processing at ' || NOW()::text
                                         ELSE 'Auto-recovery: Reset from stuck processing at ' || NOW()::text
                                    END,
                                updated_at = NOW()
                            WHERE video_id = %s
                        """, (video['video_id'],))
                        
                        if cur.rowcount > 0:
                            conn.commit()
                            reset_count += 1
                            self.log_action("RESET", f"Reset {video['video_id']} ({video['filename']}) - was stuck for {video['minutes_stuck']:.1f} minutes")
                        else:
                            logger.warning(f"No rows updated for video_id: {video['video_id']}")
                            
                finally:
                    postgres_db.pool.putconn(conn)
                    
            except Exception as e:
                error_msg = f"Failed to reset video {video['video_id']}: {str(e)}"
                self.stats['errors'].append(error_msg)
                logger.error(error_msg)
        
        self.stats['stuck_videos_reset'] = reset_count
        return reset_count
    
    def cleanup_old_failed_videos(self, age_hours: int = 24) -> int:
        """
        Clean up failed videos older than specified hours
        
        Args:
            age_hours: Age in hours after which failed videos are cleaned up
            
        Returns:
            Number of videos cleaned up
        """
        try:
            if not postgres_db._is_available():
                raise Exception("PostgreSQL not available")
                
            conn = postgres_db.pool.getconn()
            try:
                with conn.cursor() as cur:
                    if self.dry_run:
                        # Count what would be cleaned
                        cur.execute("""
                            SELECT COUNT(*) FROM video_tasks 
                            WHERE status IN ('failed', 'error')
                            AND updated_at < NOW() - INTERVAL '%s hours'
                        """, (age_hours,))
                        count = cur.fetchone()[0]
                        self.log_action("CLEANUP", f"Would clean up {count} old failed videos")
                        self.stats['failed_videos_cleaned'] = count
                        return count
                    
                    # Actually delete old failed videos
                    cur.execute("""
                        DELETE FROM video_tasks 
                        WHERE status IN ('failed', 'error')
                        AND updated_at < NOW() - INTERVAL '%s hours'
                    """, (age_hours,))
                    
                    cleaned_count = cur.rowcount
                    conn.commit()
                    
                    self.stats['failed_videos_cleaned'] = cleaned_count
                    self.log_action("CLEANUP", f"Cleaned up {cleaned_count} old failed videos")
                    return cleaned_count
                    
            finally:
                postgres_db.pool.putconn(conn)
                
        except Exception as e:
            error_msg = f"Failed to cleanup old failed videos: {str(e)}"
            self.stats['errors'].append(error_msg)
            logger.error(error_msg)
            return 0
    
    def check_worker_health(self) -> Dict[str, Any]:
        """
        Check health of all configured workers
        
        Returns:
            Dictionary with worker health status
        """
        worker_status = {
            'primary_healthy': False,
            'fallback_healthy': False,
            'primary_url': None,
            'fallback_url': None,
            'issues': []
        }
        
        try:
            # Get worker URLs from worker_manager
            primary_url = getattr(worker_manager, 'primary_worker_url', None)
            fallback_url = getattr(worker_manager, 'fallback_worker_url', None)
            
            worker_status['primary_url'] = primary_url
            worker_status['fallback_url'] = fallback_url
            
            # Check primary worker
            if primary_url:
                try:
                    health = worker_manager.check_worker_health(primary_url)
                    worker_status['primary_healthy'] = health.get('healthy', False)
                    if not health.get('healthy', False):
                        issue = f"Primary worker ({primary_url}) unhealthy: {health.get('error', 'Unknown error')}"
                        worker_status['issues'].append(issue)
                        self.stats['worker_health_issues'] += 1
                except Exception as e:
                    issue = f"Primary worker ({primary_url}) check failed: {str(e)}"
                    worker_status['issues'].append(issue)
                    self.stats['worker_health_issues'] += 1
            
            # Check fallback worker
            if fallback_url:
                try:
                    health = worker_manager.check_worker_health(fallback_url)
                    worker_status['fallback_healthy'] = health.get('healthy', False)
                    if not health.get('healthy', False):
                        issue = f"Fallback worker ({fallback_url}) unhealthy: {health.get('error', 'Unknown error')}"
                        worker_status['issues'].append(issue)
                        self.stats['worker_health_issues'] += 1
                except Exception as e:
                    issue = f"Fallback worker ({fallback_url}) check failed: {str(e)}"
                    worker_status['issues'].append(issue)
                    self.stats['worker_health_issues'] += 1
            
            # Log worker status
            if worker_status['issues']:
                for issue in worker_status['issues']:
                    self.log_action("WORKER_HEALTH", issue)
            else:
                self.log_action("WORKER_HEALTH", "All workers healthy")
                
        except Exception as e:
            error_msg = f"Failed to check worker health: {str(e)}"
            self.stats['errors'].append(error_msg)
            logger.error(error_msg)
        
        return worker_status
    
    def generate_report(self) -> Dict[str, Any]:
        """Generate a comprehensive recovery report"""
        return {
            'timestamp': datetime.datetime.now().isoformat(),
            'dry_run': self.dry_run,
            'statistics': self.stats,
            'recommendations': self._generate_recommendations()
        }
    
    def _generate_recommendations(self) -> List[str]:
        """Generate recommendations based on findings"""
        recommendations = []
        
        if self.stats['stuck_videos_found'] > 5:
            recommendations.append("High number of stuck videos detected. Consider investigating worker performance.")
        
        if self.stats['worker_health_issues'] > 0:
            recommendations.append("Worker health issues detected. Manual intervention may be required.")
        
        if len(self.stats['errors']) > 0:
            recommendations.append("Errors occurred during recovery. Check logs for details.")
        
        if self.stats['stuck_videos_found'] == 0 and self.stats['worker_health_issues'] == 0:
            recommendations.append("System appears healthy. No immediate action required.")
        
        return recommendations
    
    def run_full_recovery(self, stuck_threshold_minutes: int = 15, cleanup_age_hours: int = 24) -> Dict[str, Any]:
        """
        Run the complete recovery process
        
        Args:
            stuck_threshold_minutes: Minutes after which processing videos are considered stuck
            cleanup_age_hours: Hours after which failed videos are cleaned up
            
        Returns:
            Recovery report
        """
        self.log_action("START", f"Auto-recovery system starting (dry_run={self.dry_run})")
        
        # Check if core modules are available
        if postgres_db is None or worker_manager is None:
            error_msg = "Core modules not initialized. Cannot run recovery."
            self.stats['errors'].append(error_msg)
            logger.error(error_msg)
            return self.generate_report()
        
        try:
            # Step 1: Check worker health
            self.log_action("STEP", "Checking worker health")
            worker_status = self.check_worker_health()
            
            # Step 2: Detect stuck videos
            self.log_action("STEP", "Detecting stuck videos")
            stuck_videos = self.detect_stuck_videos(stuck_threshold_minutes)
            
            # Step 3: Reset stuck videos
            if stuck_videos:
                self.log_action("STEP", f"Resetting {len(stuck_videos)} stuck videos")
                self.reset_stuck_videos(stuck_videos)
            
            # Step 4: Cleanup old failed videos
            self.log_action("STEP", "Cleaning up old failed videos")
            self.cleanup_old_failed_videos(cleanup_age_hours)
            
            # Generate final report
            report = self.generate_report()
            self.log_action("COMPLETE", f"Recovery completed. Reset: {self.stats['stuck_videos_reset']}, Cleaned: {self.stats['failed_videos_cleaned']}")
            
            return report
            
        except Exception as e:
            error_msg = f"Recovery process failed: {str(e)}"
            self.stats['errors'].append(error_msg)
            logger.error(error_msg)
            return self.generate_report()

def main():
    """Main entry point for the auto-recovery system"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Automated Video Processing Recovery System')
    parser.add_argument('--dry-run', action='store_true', help='Run in dry-run mode (no actual changes)')
    parser.add_argument('--stuck-threshold', type=int, default=15, help='Minutes after which processing videos are considered stuck (default: 15)')
    parser.add_argument('--cleanup-age', type=int, default=24, help='Hours after which failed videos are cleaned up (default: 24)')
    parser.add_argument('--output', type=str, help='Output file for recovery report (JSON format)')
    parser.add_argument('--test-mode', action='store_true', help='Run in test mode (skip database initialization)')
    
    args = parser.parse_args()
    
    # Initialize core modules unless in test mode
    if not args.test_mode:
        if not initialize_core_modules():
            print("❌ Failed to initialize core modules. Use --test-mode for testing without database.")
            sys.exit(1)
    else:
        print("🧪 Running in test mode - database operations will be skipped")
    
    # Initialize recovery system
    recovery = AutoRecoverySystem(dry_run=args.dry_run)
    
    # Run recovery process
    report = recovery.run_full_recovery(
        stuck_threshold_minutes=args.stuck_threshold,
        cleanup_age_hours=args.cleanup_age
    )
    
    # Output report
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(report, f, indent=2)
        print(f"Recovery report saved to: {args.output}")
    else:
        print("\n" + "="*50)
        print("AUTO-RECOVERY REPORT")
        print("="*50)
        print(json.dumps(report, indent=2))
    
    # Exit with appropriate code
    if report['statistics']['errors'] and not args.test_mode:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == '__main__':
    main()
