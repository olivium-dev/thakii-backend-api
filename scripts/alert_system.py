#!/usr/bin/env python3
"""
Automated Alerting System for Critical Failures
==============================================

This script provides automated alerting for critical system failures.
It's designed to be integrated into GitHub Actions pipelines to notify about issues.

Features:
- Monitors system health metrics
- Sends alerts via multiple channels (GitHub Issues, Slack, Email)
- Escalates critical issues
- Maintains alert history
- Prevents alert spam with rate limiting
"""

import os
import sys
import json
import datetime
import logging
import requests
import hashlib
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from enum import Enum

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/tmp/alert_system.log')
    ]
)
logger = logging.getLogger(__name__)

class AlertSeverity(Enum):
    """Alert severity levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class AlertChannel(Enum):
    """Available alert channels"""
    GITHUB_ISSUE = "github_issue"
    SLACK = "slack"
    EMAIL = "email"
    WEBHOOK = "webhook"

@dataclass
class Alert:
    """Alert data structure"""
    title: str
    message: str
    severity: AlertSeverity
    component: str
    timestamp: str
    details: Dict[str, Any]
    alert_id: str = ""
    
    def __post_init__(self):
        if not self.alert_id:
            # Generate unique alert ID based on content
            content = f"{self.title}:{self.component}:{self.severity.value}"
            self.alert_id = hashlib.md5(content.encode()).hexdigest()[:8]

class AlertSystem:
    """Automated alerting system"""
    
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.github_token = os.getenv('GITHUB_TOKEN')
        self.github_repo = os.getenv('GITHUB_REPOSITORY', 'olivium-dev/thakii-infrastructure-fix')
        self.slack_webhook = os.getenv('SLACK_WEBHOOK_URL')
        self.alert_history_file = '/tmp/alert_history.json'
        self.rate_limit_minutes = 60  # Don't send same alert more than once per hour
        
        self.stats = {
            'alerts_generated': 0,
            'alerts_sent': 0,
            'alerts_suppressed': 0,
            'errors': []
        }
    
    def log_action(self, action: str, details: str = ""):
        """Log actions with dry-run indication"""
        prefix = "[DRY-RUN] " if self.dry_run else "[LIVE] "
        logger.info(f"{prefix}{action}: {details}")
    
    def load_alert_history(self) -> Dict[str, Any]:
        """Load alert history from file"""
        try:
            if os.path.exists(self.alert_history_file):
                with open(self.alert_history_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load alert history: {e}")
        
        return {'alerts': {}}
    
    def save_alert_history(self, history: Dict[str, Any]):
        """Save alert history to file"""
        try:
            with open(self.alert_history_file, 'w') as f:
                json.dump(history, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save alert history: {e}")
    
    def should_send_alert(self, alert: Alert) -> bool:
        """Check if alert should be sent based on rate limiting"""
        history = self.load_alert_history()
        
        if alert.alert_id in history['alerts']:
            last_sent = datetime.datetime.fromisoformat(history['alerts'][alert.alert_id]['last_sent'])
            time_diff = datetime.datetime.now() - last_sent
            
            if time_diff.total_seconds() < (self.rate_limit_minutes * 60):
                self.log_action("RATE_LIMIT", f"Alert {alert.alert_id} suppressed (sent {time_diff.total_seconds():.0f}s ago)")
                self.stats['alerts_suppressed'] += 1
                return False
        
        return True
    
    def record_alert_sent(self, alert: Alert):
        """Record that an alert was sent"""
        history = self.load_alert_history()
        history['alerts'][alert.alert_id] = {
            'title': alert.title,
            'component': alert.component,
            'severity': alert.severity.value,
            'last_sent': datetime.datetime.now().isoformat(),
            'send_count': history['alerts'].get(alert.alert_id, {}).get('send_count', 0) + 1
        }
        self.save_alert_history(history)
    
    def create_github_issue(self, alert: Alert) -> bool:
        """Create a GitHub issue for the alert"""
        if not self.github_token:
            self.log_action("GITHUB_SKIP", "No GitHub token provided")
            return False
        
        try:
            if self.dry_run:
                self.log_action("GITHUB_ISSUE", f"Would create issue: {alert.title}")
                return True
            
            # Format issue body
            body = f"""## 🚨 {alert.severity.value.upper()} Alert

**Component:** {alert.component}
**Timestamp:** {alert.timestamp}
**Alert ID:** {alert.alert_id}

### Description
{alert.message}

### Details
```json
{json.dumps(alert.details, indent=2)}
```

### Automated Response
This issue was automatically created by the Thakii monitoring system.

**Severity:** {alert.severity.value}
**Next Steps:** 
- Investigate the component: {alert.component}
- Check system logs and monitoring dashboards
- Apply appropriate fixes based on the alert details

---
*This is an automated alert. Please investigate promptly.*
"""
            
            # Create issue via GitHub API
            url = f"https://api.github.com/repos/{self.github_repo}/issues"
            headers = {
                'Authorization': f'token {self.github_token}',
                'Accept': 'application/vnd.github.v3+json'
            }
            
            data = {
                'title': f"🚨 {alert.severity.value.upper()}: {alert.title}",
                'body': body,
                'labels': [
                    'alert',
                    f'severity-{alert.severity.value}',
                    f'component-{alert.component.lower().replace(" ", "-")}'
                ]
            }
            
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            if response.status_code == 201:
                issue_url = response.json().get('html_url')
                self.log_action("GITHUB_ISSUE", f"Created issue: {issue_url}")
                return True
            else:
                self.log_action("GITHUB_ERROR", f"Failed to create issue: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            error_msg = f"Failed to create GitHub issue: {str(e)}"
            self.stats['errors'].append(error_msg)
            logger.error(error_msg)
            return False
    
    def send_slack_alert(self, alert: Alert) -> bool:
        """Send alert to Slack"""
        if not self.slack_webhook:
            self.log_action("SLACK_SKIP", "No Slack webhook provided")
            return False
        
        try:
            if self.dry_run:
                self.log_action("SLACK_ALERT", f"Would send Slack alert: {alert.title}")
                return True
            
            # Choose emoji based on severity
            emoji_map = {
                AlertSeverity.LOW: "🟡",
                AlertSeverity.MEDIUM: "🟠", 
                AlertSeverity.HIGH: "🔴",
                AlertSeverity.CRITICAL: "🚨"
            }
            
            emoji = emoji_map.get(alert.severity, "⚠️")
            
            # Format Slack message
            slack_data = {
                "text": f"{emoji} Thakii System Alert",
                "attachments": [
                    {
                        "color": "danger" if alert.severity in [AlertSeverity.HIGH, AlertSeverity.CRITICAL] else "warning",
                        "title": f"{alert.severity.value.upper()}: {alert.title}",
                        "fields": [
                            {
                                "title": "Component",
                                "value": alert.component,
                                "short": True
                            },
                            {
                                "title": "Timestamp",
                                "value": alert.timestamp,
                                "short": True
                            },
                            {
                                "title": "Alert ID",
                                "value": alert.alert_id,
                                "short": True
                            },
                            {
                                "title": "Message",
                                "value": alert.message,
                                "short": False
                            }
                        ],
                        "footer": "Thakii Monitoring System",
                        "ts": int(datetime.datetime.now().timestamp())
                    }
                ]
            }
            
            response = requests.post(self.slack_webhook, json=slack_data, timeout=30)
            
            if response.status_code == 200:
                self.log_action("SLACK_ALERT", f"Sent Slack alert: {alert.title}")
                return True
            else:
                self.log_action("SLACK_ERROR", f"Failed to send Slack alert: {response.status_code}")
                return False
                
        except Exception as e:
            error_msg = f"Failed to send Slack alert: {str(e)}"
            self.stats['errors'].append(error_msg)
            logger.error(error_msg)
            return False
    
    def send_alert(self, alert: Alert, channels: List[AlertChannel] = None) -> bool:
        """Send alert through specified channels"""
        if channels is None:
            # Default channels based on severity
            if alert.severity == AlertSeverity.CRITICAL:
                channels = [AlertChannel.GITHUB_ISSUE, AlertChannel.SLACK]
            elif alert.severity == AlertSeverity.HIGH:
                channels = [AlertChannel.GITHUB_ISSUE, AlertChannel.SLACK]
            elif alert.severity == AlertSeverity.MEDIUM:
                channels = [AlertChannel.SLACK]
            else:
                channels = [AlertChannel.SLACK]
        
        self.stats['alerts_generated'] += 1
        
        # Check rate limiting
        if not self.should_send_alert(alert):
            return False
        
        success = False
        
        # Send through each channel
        for channel in channels:
            try:
                if channel == AlertChannel.GITHUB_ISSUE:
                    if self.create_github_issue(alert):
                        success = True
                elif channel == AlertChannel.SLACK:
                    if self.send_slack_alert(alert):
                        success = True
                # Add more channels here as needed
                
            except Exception as e:
                error_msg = f"Failed to send alert via {channel.value}: {str(e)}"
                self.stats['errors'].append(error_msg)
                logger.error(error_msg)
        
        if success:
            self.stats['alerts_sent'] += 1
            self.record_alert_sent(alert)
            self.log_action("ALERT_SENT", f"Alert {alert.alert_id} sent successfully")
        
        return success
    
    def analyze_recovery_report(self, report_file: str) -> List[Alert]:
        """Analyze recovery report and generate alerts"""
        alerts = []
        
        try:
            with open(report_file, 'r') as f:
                report = json.load(f)
            
            stats = report.get('statistics', {})
            
            # Alert for stuck videos
            stuck_count = stats.get('stuck_videos_found', 0)
            if stuck_count > 0:
                severity = AlertSeverity.HIGH if stuck_count > 10 else AlertSeverity.MEDIUM
                alerts.append(Alert(
                    title=f"{stuck_count} Videos Stuck in Processing",
                    message=f"Found {stuck_count} videos stuck in processing state. These have been automatically reset to 'in_queue' for retry.",
                    severity=severity,
                    component="Video Processing",
                    timestamp=datetime.datetime.now().isoformat(),
                    details={
                        'stuck_videos_found': stuck_count,
                        'stuck_videos_reset': stats.get('stuck_videos_reset', 0),
                        'report_file': report_file
                    }
                ))
            
            # Alert for worker health issues
            worker_issues = stats.get('worker_health_issues', 0)
            if worker_issues > 0:
                alerts.append(Alert(
                    title=f"Worker Health Issues Detected",
                    message=f"Found {worker_issues} worker health issues. Manual intervention may be required.",
                    severity=AlertSeverity.HIGH,
                    component="Worker Services",
                    timestamp=datetime.datetime.now().isoformat(),
                    details={
                        'worker_health_issues': worker_issues,
                        'report_file': report_file
                    }
                ))
            
            # Alert for errors
            errors = stats.get('errors', [])
            if errors:
                alerts.append(Alert(
                    title=f"Recovery System Errors",
                    message=f"Recovery system encountered {len(errors)} errors during execution.",
                    severity=AlertSeverity.MEDIUM,
                    component="Recovery System",
                    timestamp=datetime.datetime.now().isoformat(),
                    details={
                        'error_count': len(errors),
                        'errors': errors[:5],  # Include first 5 errors
                        'report_file': report_file
                    }
                ))
            
        except Exception as e:
            # Alert for report analysis failure
            alerts.append(Alert(
                title="Failed to Analyze Recovery Report",
                message=f"Could not analyze recovery report: {str(e)}",
                severity=AlertSeverity.MEDIUM,
                component="Alert System",
                timestamp=datetime.datetime.now().isoformat(),
                details={
                    'error': str(e),
                    'report_file': report_file
                }
            ))
        
        return alerts
    
    def analyze_worker_monitor_report(self, report_file: str) -> List[Alert]:
        """Analyze worker monitoring report and generate alerts"""
        alerts = []
        
        try:
            with open(report_file, 'r') as f:
                report = json.load(f)
            
            stats = report.get('statistics', {})
            server_type = report.get('server_type', 'unknown')
            
            # Alert for service restarts
            restarts = stats.get('services_restarted', 0)
            if restarts > 0:
                alerts.append(Alert(
                    title=f"Worker Services Restarted ({server_type})",
                    message=f"{restarts} worker services were automatically restarted due to health issues.",
                    severity=AlertSeverity.MEDIUM,
                    component=f"Worker Services ({server_type})",
                    timestamp=datetime.datetime.now().isoformat(),
                    details={
                        'services_restarted': restarts,
                        'server_type': server_type,
                        'report_file': report_file
                    }
                ))
            
            # Alert for tunnel reconnections (Mac only)
            tunnel_reconnections = stats.get('tunnel_reconnections', 0)
            if tunnel_reconnections > 0:
                alerts.append(Alert(
                    title=f"PostgreSQL Tunnel Reconnected ({server_type})",
                    message=f"PostgreSQL tunnel was reconnected {tunnel_reconnections} times. Check tunnel stability.",
                    severity=AlertSeverity.MEDIUM,
                    component=f"PostgreSQL Tunnel ({server_type})",
                    timestamp=datetime.datetime.now().isoformat(),
                    details={
                        'tunnel_reconnections': tunnel_reconnections,
                        'server_type': server_type,
                        'report_file': report_file
                    }
                ))
            
            # Alert for monitoring errors
            errors = stats.get('errors', [])
            if errors:
                alerts.append(Alert(
                    title=f"Worker Monitoring Errors ({server_type})",
                    message=f"Worker monitoring encountered {len(errors)} errors during execution.",
                    severity=AlertSeverity.MEDIUM,
                    component=f"Worker Monitoring ({server_type})",
                    timestamp=datetime.datetime.now().isoformat(),
                    details={
                        'error_count': len(errors),
                        'errors': errors[:5],  # Include first 5 errors
                        'server_type': server_type,
                        'report_file': report_file
                    }
                ))
            
        except Exception as e:
            # Alert for report analysis failure
            alerts.append(Alert(
                title="Failed to Analyze Worker Monitor Report",
                message=f"Could not analyze worker monitoring report: {str(e)}",
                severity=AlertSeverity.MEDIUM,
                component="Alert System",
                timestamp=datetime.datetime.now().isoformat(),
                details={
                    'error': str(e),
                    'report_file': report_file
                }
            ))
        
        return alerts
    
    def generate_report(self) -> Dict[str, Any]:
        """Generate alerting system report"""
        return {
            'timestamp': datetime.datetime.now().isoformat(),
            'dry_run': self.dry_run,
            'statistics': self.stats,
            'configuration': {
                'github_repo': self.github_repo,
                'github_token_configured': bool(self.github_token),
                'slack_webhook_configured': bool(self.slack_webhook),
                'rate_limit_minutes': self.rate_limit_minutes
            }
        }

def main():
    """Main entry point for the alert system"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Automated Alerting System for Critical Failures')
    parser.add_argument('--dry-run', action='store_true', help='Run in dry-run mode (no actual alerts sent)')
    parser.add_argument('--recovery-report', type=str, help='Recovery report file to analyze')
    parser.add_argument('--worker-report', type=str, help='Worker monitoring report file to analyze')
    parser.add_argument('--output', type=str, help='Output file for alert system report (JSON format)')
    
    args = parser.parse_args()
    
    # Initialize alert system
    alert_system = AlertSystem(dry_run=args.dry_run)
    
    alerts_sent = 0
    
    # Analyze recovery report if provided
    if args.recovery_report:
        if os.path.exists(args.recovery_report):
            recovery_alerts = alert_system.analyze_recovery_report(args.recovery_report)
            for alert in recovery_alerts:
                if alert_system.send_alert(alert):
                    alerts_sent += 1
        else:
            logger.warning(f"Recovery report file not found: {args.recovery_report}")
    
    # Analyze worker monitoring report if provided
    if args.worker_report:
        if os.path.exists(args.worker_report):
            worker_alerts = alert_system.analyze_worker_monitor_report(args.worker_report)
            for alert in worker_alerts:
                if alert_system.send_alert(alert):
                    alerts_sent += 1
        else:
            logger.warning(f"Worker monitoring report file not found: {args.worker_report}")
    
    # Generate final report
    report = alert_system.generate_report()
    
    # Output report
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(report, f, indent=2)
        print(f"Alert system report saved to: {args.output}")
    else:
        print("\n" + "="*50)
        print("ALERT SYSTEM REPORT")
        print("="*50)
        print(json.dumps(report, indent=2))
    
    print(f"\n📊 Summary: {alerts_sent} alerts sent")
    
    # Exit with appropriate code
    if report['statistics']['errors']:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == '__main__':
    main()
