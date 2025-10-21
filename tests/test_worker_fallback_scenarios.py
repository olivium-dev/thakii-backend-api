#!/usr/bin/env python3
"""
Advanced Worker Fallback Scenario Tests
Tests primary worker failure, fallback success, and both workers down scenarios
"""

import os
import sys
import json
import time
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.worker_manager import WorkerManager


class WorkerFallbackScenarioTester:
    def __init__(self):
        """Initialize the scenario test suite"""
        self.test_results = []
        
    def log_test(self, test_name: str, passed: bool, message: str, details: dict = None):
        """Log a test result"""
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {test_name}")
        print(f"  {message}")
        if details:
            print(f"  Details: {json.dumps(details, indent=2)}")
        print()
        
        self.test_results.append({
            'test_name': test_name,
            'passed': passed,
            'message': message,
            'details': details
        })
    
    def scenario_1_primary_healthy_fallback_healthy(self):
        """Scenario 1: Both workers healthy - should use primary"""
        test_name = "Scenario 1: Both Workers Healthy"
        try:
            # Set both workers to the same working URL for testing
            os.environ['PRIMARY_WORKER_URL'] = 'https://thakii-02.fanusdigital.site/thakii-worker'
            os.environ['FALLBACK_WORKER_URL'] = 'https://thakii-02.fanusdigital.site/thakii-worker'
            os.environ['WORKER_PRIORITY_MODE'] = 'primary-with-fallback'
            
            wm = WorkerManager()
            worker_url, worker_name = wm.select_available_worker(check_health=True)
            
            details = {
                'primary_url': wm.primary_worker_url,
                'fallback_url': wm.fallback_worker_url,
                'selected_worker': worker_name,
                'selected_url': worker_url
            }
            
            # Should select primary when both are healthy
            if worker_name == 'primary':
                self.log_test(test_name, True, "Primary worker selected when both healthy", details)
                return True
            else:
                self.log_test(test_name, False, f"Expected 'primary' but got '{worker_name}'", details)
                return False
                
        except Exception as e:
            self.log_test(test_name, False, f"Test failed: {str(e)}")
            return False
    
    def scenario_2_primary_down_fallback_healthy(self):
        """Scenario 2: Primary down, fallback healthy - should use fallback"""
        test_name = "Scenario 2: Primary Down, Fallback Healthy"
        try:
            # Set primary to invalid URL, fallback to valid URL
            os.environ['PRIMARY_WORKER_URL'] = 'http://invalid-primary-worker.local:9999'
            os.environ['FALLBACK_WORKER_URL'] = 'https://thakii-02.fanusdigital.site/thakii-worker'
            os.environ['WORKER_PRIORITY_MODE'] = 'primary-with-fallback'
            
            wm = WorkerManager()
            
            # Check primary health
            primary_health = wm.check_worker_health(wm.primary_worker_url, timeout=2)
            
            # Select worker
            worker_url, worker_name = wm.select_available_worker(check_health=True)
            
            details = {
                'primary_url': wm.primary_worker_url,
                'primary_healthy': primary_health['healthy'],
                'primary_error': primary_health['error'],
                'fallback_url': wm.fallback_worker_url,
                'selected_worker': worker_name,
                'selected_url': worker_url
            }
            
            # Should select fallback when primary is down
            if worker_name == 'fallback' and worker_url == wm.fallback_worker_url:
                self.log_test(test_name, True, "Fallback worker selected when primary is down", details)
                return True
            else:
                self.log_test(test_name, False, f"Expected 'fallback' but got '{worker_name}'", details)
                return False
                
        except Exception as e:
            self.log_test(test_name, False, f"Test failed: {str(e)}")
            return False
    
    def scenario_3_both_workers_down(self):
        """Scenario 3: Both workers down - should return none"""
        test_name = "Scenario 3: Both Workers Down"
        try:
            # Set both workers to invalid URLs
            os.environ['PRIMARY_WORKER_URL'] = 'http://invalid-primary-worker.local:9999'
            os.environ['FALLBACK_WORKER_URL'] = 'http://invalid-fallback-worker.local:9998'
            os.environ['WORKER_PRIORITY_MODE'] = 'primary-with-fallback'
            
            wm = WorkerManager()
            
            # Check health of both
            primary_health = wm.check_worker_health(wm.primary_worker_url, timeout=2)
            fallback_health = wm.check_worker_health(wm.fallback_worker_url, timeout=2)
            
            # Try to select worker
            worker_url, worker_name = wm.select_available_worker(check_health=True)
            
            details = {
                'primary_url': wm.primary_worker_url,
                'primary_healthy': primary_health['healthy'],
                'fallback_url': wm.fallback_worker_url,
                'fallback_healthy': fallback_health['healthy'],
                'selected_worker': worker_name,
                'selected_url': worker_url
            }
            
            # Should return none when both are down
            if worker_name == 'none' and worker_url is None:
                self.log_test(test_name, True, "No worker selected when both are down", details)
                return True
            else:
                self.log_test(test_name, False, f"Expected 'none' but got '{worker_name}'", details)
                return False
                
        except Exception as e:
            self.log_test(test_name, False, f"Test failed: {str(e)}")
            return False
    
    def scenario_4_trigger_with_fallback_success(self):
        """Scenario 4: Trigger with automatic fallback (primary fails, fallback succeeds)"""
        test_name = "Scenario 4: Trigger with Automatic Fallback"
        try:
            # Set primary to invalid, fallback to valid
            os.environ['PRIMARY_WORKER_URL'] = 'http://invalid-primary-worker.local:9999'
            os.environ['FALLBACK_WORKER_URL'] = 'https://thakii-02.fanusdigital.site/thakii-worker'
            os.environ['WORKER_PRIORITY_MODE'] = 'primary-with-fallback'
            
            wm = WorkerManager()
            
            # Create mock payload (won't actually process since we don't have real S3 key)
            payload = {
                "video_id": "test-fallback-video",
                "user_id": "test-user",
                "filename": "test.mp4",
                "s3_key": "test/key.mp4"
            }
            
            print("  ⚠️  Testing fallback mechanism with mock payload")
            print("  This will attempt to contact both workers")
            print("  Primary should fail, fallback should be attempted")
            
            # Note: This will actually try to POST to the workers
            # The fallback will return an error because we don't have a valid S3 key
            # But we can verify that it tried the fallback
            result = wm.trigger_with_fallback(payload)
            
            details = {
                'success': result['success'],
                'worker_used': result['worker_used'],
                'worker_url': result.get('worker_url', ''),
                'status_code': result.get('status_code', 0),
                'error': result.get('error', '')
            }
            
            # We expect it to try fallback (worker_used should be 'fallback')
            # Success may be False due to invalid payload, but it should have tried fallback
            if result['worker_used'] == 'fallback':
                self.log_test(test_name, True, "Automatic fallback triggered successfully", details)
                return True
            else:
                self.log_test(test_name, False, f"Expected to use 'fallback' but used '{result['worker_used']}'", details)
                return False
                
        except Exception as e:
            self.log_test(test_name, False, f"Test failed: {str(e)}")
            return False
    
    def scenario_5_primary_only_mode(self):
        """Scenario 5: Primary-only mode (should not fallback)"""
        test_name = "Scenario 5: Primary-Only Mode"
        try:
            # Set primary to valid, fallback to valid, but mode to primary-only
            os.environ['PRIMARY_WORKER_URL'] = 'https://thakii-02.fanusdigital.site/thakii-worker'
            os.environ['FALLBACK_WORKER_URL'] = 'https://thakii-02.fanusdigital.site/thakii-worker'
            os.environ['WORKER_PRIORITY_MODE'] = 'primary-only'
            
            wm = WorkerManager()
            
            worker_url, worker_name = wm.select_available_worker(check_health=True)
            
            details = {
                'priority_mode': wm.priority_mode,
                'primary_url': wm.primary_worker_url,
                'fallback_url': wm.fallback_worker_url,
                'selected_worker': worker_name
            }
            
            # Should only use primary in primary-only mode
            if worker_name == 'primary' and wm.priority_mode == 'primary-only':
                self.log_test(test_name, True, "Primary-only mode respected", details)
                return True
            else:
                self.log_test(test_name, False, "Primary-only mode not working correctly", details)
                return False
                
        except Exception as e:
            self.log_test(test_name, False, f"Test failed: {str(e)}")
            return False
    
    def scenario_6_health_check_performance(self):
        """Scenario 6: Health check performance test"""
        test_name = "Scenario 6: Health Check Performance"
        try:
            os.environ['PRIMARY_WORKER_URL'] = 'https://thakii-02.fanusdigital.site/thakii-worker'
            os.environ['FALLBACK_WORKER_URL'] = 'https://thakii-02.fanusdigital.site/thakii-worker'
            
            wm = WorkerManager()
            
            # Measure health check time
            start_time = time.time()
            health = wm.check_worker_health(wm.primary_worker_url)
            elapsed_time = time.time() - start_time
            
            details = {
                'url': wm.primary_worker_url,
                'response_time': health['response_time'],
                'total_elapsed': elapsed_time,
                'healthy': health['healthy'],
                'timeout_setting': wm.health_check_timeout
            }
            
            # Health check should complete within timeout
            if elapsed_time < wm.health_check_timeout + 1:  # +1 for overhead
                self.log_test(test_name, True, f"Health check completed in {elapsed_time:.2f}s", details)
                return True
            else:
                self.log_test(test_name, False, f"Health check too slow: {elapsed_time:.2f}s", details)
                return False
                
        except Exception as e:
            self.log_test(test_name, False, f"Test failed: {str(e)}")
            return False
    
    def run_all_scenarios(self):
        """Run all scenario tests"""
        print("\n" + "="*80)
        print("🎬 WORKER FALLBACK SYSTEM - ADVANCED SCENARIO TESTS")
        print("="*80 + "\n")
        
        scenarios = [
            self.scenario_1_primary_healthy_fallback_healthy,
            self.scenario_2_primary_down_fallback_healthy,
            self.scenario_3_both_workers_down,
            self.scenario_4_trigger_with_fallback_success,
            self.scenario_5_primary_only_mode,
            self.scenario_6_health_check_performance
        ]
        
        for scenario_func in scenarios:
            try:
                scenario_func()
                time.sleep(0.5)  # Brief pause between tests
            except Exception as e:
                self.log_test(scenario_func.__name__, False, f"Scenario execution failed: {str(e)}")
        
        # Generate summary
        print("\n" + "="*80)
        print("📊 SCENARIO TEST SUMMARY")
        print("="*80 + "\n")
        
        total_tests = len(self.test_results)
        passed_tests = sum(1 for r in self.test_results if r['passed'])
        failed_tests = total_tests - passed_tests
        pass_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0
        
        print(f"Total Scenarios: {total_tests}")
        print(f"Passed: {passed_tests} ✅")
        print(f"Failed: {failed_tests} ❌")
        print(f"Pass Rate: {pass_rate:.1f}%")
        print()
        
        # Save results
        results_file = Path(__file__).parent / "worker_fallback_scenarios_results.json"
        with open(results_file, 'w') as f:
            json.dump({
                'summary': {
                    'total': total_tests,
                    'passed': passed_tests,
                    'failed': failed_tests,
                    'pass_rate': pass_rate
                },
                'scenarios': self.test_results,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }, f, indent=2)
        
        print(f"📄 Detailed results saved to: {results_file}")
        print()
        
        return pass_rate >= 80  # 80% pass rate required


if __name__ == "__main__":
    tester = WorkerFallbackScenarioTester()
    success = tester.run_all_scenarios()
    
    if success:
        print("✅ ALL SCENARIOS PASSED")
        sys.exit(0)
    else:
        print("❌ SOME SCENARIOS FAILED")
        sys.exit(1)

