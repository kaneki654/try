#!/usr/bin/env python3
"""
HTTP Siege Mode Tester - Continuous load until critical errors occur
Educational tool to demonstrate server resilience under sustained load.
FOR EDUCATIONAL PURPOSES ONLY - Use only on systems you own or have explicit permission to test.
"""

import requests
import time
import sys
import threading
import random
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Set
import signal
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from dataclasses import dataclass, asdict
from collections import defaultdict, deque
import statistics

@dataclass
class SiegeResult:
    """Container for siege mode results."""
    timestamp: str
    request_count: int
    status_code: int
    response_time: float
    thread_id: int
    error: bool = False
    fatal_error: bool = False

class SiegeModeTester:
    """Continuous load tester that runs until critical errors are detected."""
    
    # Error codes that will stop the siege
    FATAL_ERROR_CODES = {500, 502, 503, 504}
    
    def __init__(self):
        self.running = True
        self.siege_active = False
        self.total_requests = 0
        self.results: List[SiegeResult] = []
        self.error_counts = defaultdict(int)
        self.status_distribution = defaultdict(int)
        self.response_times = []
        self.start_time = None
        self.end_time = None
        self.lock = threading.Lock()
        self.fatal_error_detected = threading.Event()
        
        # Signal handling
        signal.signal(signal.SIGINT, self.signal_handler)
    
    def signal_handler(self, signum, frame):
        """Handle interrupt signals gracefully."""
        print("\n⚠️  Siege interrupted by user. Stopping...")
        self.running = False
        self.siege_active = False
    
    def generate_headers(self) -> Dict[str, str]:
        """Generate random HTTP headers to avoid caching."""
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1'
        ]
        
        return {
            'User-Agent': random.choice(user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
            'Upgrade-Insecure-Requests': '1'
        }
    
    def check_fatal_error(self, status_code: int) -> bool:
        """Check if status code should stop the siege."""
        return status_code in self.FATAL_ERROR_CODES
    
    def siege_worker(self, url: str, thread_id: int, config: Dict):
        """Worker thread for continuous siege."""
        thread_requests = 0
        
        while self.running and self.siege_active and not self.fatal_error_detected.is_set():
            try:
                # Add cache-busting parameter
                timestamp = int(time.time() * 1000)
                siege_url = f"{url}?siege={timestamp}_{thread_id}_{thread_requests}"
                
                # Prepare headers
                headers = self.generate_headers()
                
                # Send request with timing
                start_time = time.time()
                response = requests.get(
                    siege_url,
                    headers=headers,
                    timeout=config.get('timeout', 10),
                    verify=config.get('verify_ssl', True)
                )
                response_time = time.time() - start_time
                
                # Get status code
                status_code = response.status_code
                
                # Check if this is a fatal error
                fatal_error = self.check_fatal_error(status_code)
                
                # Record result
                with self.lock:
                    self.total_requests += 1
                    thread_requests += 1
                    
                    result = SiegeResult(
                        timestamp=datetime.now().isoformat(),
                        request_count=self.total_requests,
                        status_code=status_code,
                        response_time=response_time,
                        thread_id=thread_id,
                        error=status_code >= 400,
                        fatal_error=fatal_error
                    )
                    
                    self.results.append(result)
                    self.status_distribution[status_code] += 1
                    self.response_times.append(response_time)
                    
                    if status_code >= 400:
                        self.error_counts[status_code] += 1
                
                # Display result in real-time
                self.display_request_result(result, thread_requests)
                
                # If fatal error detected, stop siege
                if fatal_error:
                    print(f"\n🚨 FATAL ERROR DETECTED: Status {status_code}")
                    print(f"   Thread {thread_id}, Request #{thread_requests}")
                    self.fatal_error_detected.set()
                    break
                
                # Dynamic delay based on response time
                if response_time > config.get('timeout', 10) * 0.8:
                    # Slow response, increase delay
                    delay = config.get('max_delay', 2.0)
                elif response_time < 0.1:
                    # Very fast response, aggressive mode
                    delay = config.get('min_delay', 0.01)
                else:
                    # Normal operation
                    delay = config.get('base_delay', 0.1)
                
                # Add some randomness
                delay += random.uniform(-0.02, 0.05)
                delay = max(delay, 0.01)
                
                time.sleep(delay)
                
            except requests.exceptions.RequestException as e:
                with self.lock:
                    self.total_requests += 1
                    thread_requests += 1
                    
                    # Create error result
                    result = SiegeResult(
                        timestamp=datetime.now().isoformat(),
                        request_count=self.total_requests,
                        status_code=0,
                        response_time=0,
                        thread_id=thread_id,
                        error=True,
                        fatal_error=True  # Connection errors are fatal
                    )
                    
                    self.results.append(result)
                    self.error_counts["ConnectionError"] += 1
                
                print(f"\n🚨 CONNECTION ERROR: {e}")
                self.fatal_error_detected.set()
                break
            
            except Exception as e:
                print(f"\n⚠️ Unexpected error in thread {thread_id}: {e}")
                time.sleep(1)  # Brief pause on unexpected errors
    
    def display_request_result(self, result: SiegeResult, thread_requests: int):
        """Display individual request result with color coding."""
        # Define colors and symbols based on status
        if result.fatal_error:
            symbol = "💀"
            color = "\033[91m"  # Red
            status_desc = "FATAL"
        elif result.error:
            symbol = "⚠️"
            color = "\033[93m"  # Yellow
            status_desc = "ERROR"
        elif result.status_code == 200:
            symbol = "✅"
            color = "\033[92m"  # Green
            status_desc = "OK"
        else:
            symbol = "ℹ️"
            color = "\033[96m"  # Cyan
            status_desc = "OTHER"
        
        # Clear line and display
        sys.stdout.write('\r')
        sys.stdout.write(
            f"{color}{symbol} Thread {result.thread_id:2d} | "
            f"Req #{thread_requests:6d} | "
            f"Total: {result.request_count:8d} | "
            f"Status: {result.status_code:3d} ({status_desc:6s}) | "
            f"Time: {result.response_time:.3f}s\033[0m"
        )
        sys.stdout.flush()
    
    def display_stats_dashboard(self):
        """Display real-time statistics dashboard."""
        if not self.results:
            return
        
        with self.lock:
            # Calculate statistics from recent requests (last 30 seconds)
            recent_time = datetime.now() - timedelta(seconds=30)
            recent_results = [
                r for r in self.results 
                if datetime.fromisoformat(r.timestamp) > recent_time
            ]
            
            if recent_results:
                recent_times = [r.response_time for r in recent_results if r.response_time > 0]
                recent_requests = len(recent_results)
                recent_errors = sum(1 for r in recent_results if r.error)
                
                if recent_times:
                    avg_time = sum(recent_times) / len(recent_times)
                    max_time = max(recent_times)
                else:
                    avg_time = max_time = 0
                
                # Current RPS
                current_rps = recent_requests / 30 if recent_requests > 0 else 0
                
                # Error rate
                error_rate = (recent_errors / recent_requests * 100) if recent_requests > 0 else 0
                
                # Display dashboard
                print("\n" + "="*80)
                print("📊 REAL-TIME SIEGE DASHBOARD")
                print("="*80)
                print(f"Total Requests: {self.total_requests:,}")
                print(f"Current RPS: {current_rps:.1f}")
                print(f"Recent Avg Response: {avg_time:.3f}s | Max: {max_time:.3f}s")
                print(f"Recent Error Rate: {error_rate:.1f}%")
                print(f"Active Threads: {self.get_active_thread_count()}")
                
                # Status code distribution
                print("\nStatus Code Distribution:")
                for code, count in sorted(self.status_distribution.items()):
                    percentage = (count / self.total_requests * 100) if self.total_requests > 0 else 0
                    bar = "█" * int(percentage / 2)
                    print(f"  {code:3d}: {count:6d} [{bar:50}] {percentage:.1f}%")
                
                print("="*80)
    
    def get_active_thread_count(self) -> int:
        """Get approximate count of active threads."""
        # This is a simplified version - in production you'd track threads differently
        return threading.active_count() - 2  # Subtract main thread and stats thread
    
    def stats_monitor(self, interval: float = 5.0):
        """Monitor thread to display periodic statistics."""
        while self.running and self.siege_active and not self.fatal_error_detected.is_set():
            time.sleep(interval)
            self.display_stats_dashboard()
    
    def run_siege(self, url: str, config: Dict):
        """Execute the siege mode attack."""
        print("\n" + "="*80)
        print("🚀 HTTP SIEGE MODE ACTIVATED")
        print("="*80)
        print(f"Target: {url}")
        print(f"Threads: {config['thread_count']}")
        print(f"Base Delay: {config['base_delay']}s")
        print(f"Timeout: {config['timeout']}s")
        print("\n⚠️  Siege will continue until one of these errors occurs:")
        print(f"   Fatal Error Codes: {', '.join(str(c) for c in self.FATAL_ERROR_CODES)}")
        print("   Or connection errors/timeouts")
        print("\nPress Ctrl+C to stop manually")
        print("="*80 + "\n")
        
        # Initialize siege
        self.siege_active = True
        self.start_time = datetime.now()
        
        # Start stats monitor thread
        stats_thread = threading.Thread(
            target=self.stats_monitor,
            args=(config.get('stats_interval', 10.0),),
            daemon=True
        )
        stats_thread.start()
        
        # Create and start siege threads
        threads = []
        for i in range(config['thread_count']):
            thread = threading.Thread(
                target=self.siege_worker,
                args=(url, i + 1, config),
                daemon=True
            )
            threads.append(thread)
            thread.start()
        
        # Wait for fatal error or manual stop
        try:
            while (self.running and self.siege_active and 
                   not self.fatal_error_detected.is_set()):
                time.sleep(0.1)
                
                # Check if all threads are dead (unexpected)
                alive_threads = sum(1 for t in threads if t.is_alive())
                if alive_threads == 0:
                    print("\n⚠️  All siege threads stopped unexpectedly!")
                    break
        except KeyboardInterrupt:
            print("\n⚠️  Siege manually stopped by user")
        
        # Cleanup
        self.siege_active = False
        self.end_time = datetime.now()
        
        # Wait for threads to finish
        for thread in threads:
            thread.join(timeout=2.0)
        
        # Final statistics
        self.display_final_report(config)
    
    def display_final_report(self, config: Dict):
        """Display comprehensive final report."""
        if not self.results:
            print("No results to report")
            return
        
        duration = (self.end_time - self.start_time).total_seconds() if self.start_time and self.end_time else 0
        
        print("\n" + "="*80)
        print("📊 SIEGE FINAL REPORT")
        print("="*80)
        
        # Summary
        print(f"\n📋 SUMMARY")
        print(f"  Target URL: {config.get('url', 'Unknown')}")
        print(f"  Siege Duration: {duration:.2f} seconds")
        print(f"  Total Requests: {self.total_requests:,}")
        print(f"  Average RPS: {self.total_requests / duration:.2f}" if duration > 0 else "  Average RPS: N/A")
        
        # Response time statistics
        if self.response_times:
            valid_times = [t for t in self.response_times if t > 0]
            if valid_times:
                print(f"\n⏱️  RESPONSE TIME STATISTICS")
                print(f"  Fastest: {min(valid_times):.4f}s")
                print(f"  Slowest: {max(valid_times):.4f}s")
                print(f"  Average: {sum(valid_times)/len(valid_times):.4f}s")
                
                # Calculate percentiles
                sorted_times = sorted(valid_times)
                p50 = sorted_times[int(len(sorted_times) * 0.5)]
                p95 = sorted_times[int(len(sorted_times) * 0.95)]
                p99 = sorted_times[int(len(sorted_times) * 0.99)]
                
                print(f"  Median (p50): {p50:.4f}s")
                print(f"  95th Percentile: {p95:.4f}s")
                print(f"  99th Percentile: {p99:.4f}s")
        
        # Status code breakdown
        print(f"\n🔢 STATUS CODE BREAKDOWN")
        total_requests = sum(self.status_distribution.values())
        for code in sorted(self.status_distribution.keys()):
            count = self.status_distribution[code]
            percentage = (count / total_requests * 100) if total_requests > 0 else 0
            
            # Color coding
            if code in self.FATAL_ERROR_CODES:
                color = "\033[91m"  # Red
                symbol = "💀"
            elif 200 <= code < 300:
                color = "\033[92m"  # Green
                symbol = "✅"
            elif 400 <= code < 500:
                color = "\033[93m"  # Yellow
                symbol = "⚠️"
            else:
                color = "\033[96m"  # Cyan
                symbol = "ℹ️"
            
            print(f"  {color}{symbol} {code:3d}: {count:8,d} requests ({percentage:.2f}%)\033[0m")
        
        # Error analysis
        if self.error_counts:
            print(f"\n⚠️  ERROR ANALYSIS")
            for error_code, count in sorted(self.error_counts.items()):
                if isinstance(error_code, int):
                    print(f"  Status {error_code}: {count:,d} times")
                else:
                    print(f"  {error_code}: {count:,d} times")
        
        # Siege outcome
        print(f"\n🎯 SIEGE OUTCOME")
        if self.fatal_error_detected.is_set():
            # Find the fatal error that stopped the siege
            fatal_results = [r for r in self.results if r.fatal_error]
            if fatal_results:
                last_fatal = fatal_results[-1]
                print(f"  🔴 SIEGE STOPPED BY FATAL ERROR")
                print(f"  Error Type: Status Code {last_fatal.status_code}")
                print(f"  Occurred at: Request #{last_fatal.request_count:,}")
                print(f"  Server held for: {duration:.2f} seconds")
                print(f"  Total requests before failure: {self.total_requests:,}")
            else:
                print(f"  🟡 SIEGE STOPPED (Connection Error)")
        else:
            print(f"  🟢 SIEGE MANUALLY STOPPED")
            print(f"  Server withstood siege for: {duration:.2f} seconds")
            print(f"  Total requests handled: {self.total_requests:,}")
            if duration > 0:
                print(f"  Average load: {self.total_requests / duration:.2f} RPS")
        
        print("="*80)
    
    def save_results(self, filename: str = None):
        """Save siege results to JSON file."""
        if not self.results:
            print("No results to save")
            return
        
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"siege_results_{timestamp}.json"
        
        data = {
            'metadata': {
                'start_time': self.start_time.isoformat() if self.start_time else None,
                'end_time': self.end_time.isoformat() if self.end_time else None,
                'duration_seconds': (self.end_time - self.start_time).total_seconds() 
                                  if self.start_time and self.end_time else 0,
                'total_requests': self.total_requests,
                'fatal_error_detected': self.fatal_error_detected.is_set()
            },
            'statistics': {
                'status_distribution': dict(self.status_distribution),
                'error_counts': dict(self.error_counts),
                'response_time_stats': {
                    'count': len(self.response_times),
                    'min': min(self.response_times) if self.response_times else 0,
                    'max': max(self.response_times) if self.response_times else 0,
                    'average': sum(self.response_times)/len(self.response_times) if self.response_times else 0
                } if self.response_times else {}
            },
            'results': [asdict(r) for r in self.results]
        }
        
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        
        print(f"\n💾 Results saved to: {filename}")

def interactive_mode():
    """Interactive mode for user-friendly configuration."""
    tester = SiegeModeTester()
    
    print("="*80)
    print("🚀 HTTP SIEGE MODE TESTER")
    print("="*80)
    print("\n⚠️  FOR EDUCATIONAL PURPOSES ONLY")
    print("⚠️  Test only systems you own or have explicit permission to test\n")
    
    # Get target URL
    url = input("Enter target URL (e.g., https://example.com): ").strip()
    if not url:
        print("URL is required!")
        sys.exit(1)
    
    # Validate URL format
    if not url.startswith(('http://', 'https://')):
        use_https = input("URL doesn't start with http/https. Use HTTPS? (y/n): ").lower() == 'y'
        url = ('https://' if use_https else 'http://') + url
    
    print(f"\n🔗 Target: {url}")
    
    # Configuration
    print("\n⚙️  SIEGE CONFIGURATION")
    print("-"*40)
    
    thread_count = int(input(f"Number of siege threads [default: 10]: ") or "10")
    base_delay = float(input(f"Base delay between requests (seconds) [default: 0.05]: ") or "0.05")
    timeout = int(input(f"Request timeout (seconds) [default: 30]: ") or "30")
    
    # Advanced options
    print("\n🔧 ADVANCED OPTIONS")
    print("-"*40)
    
    min_delay = float(input(f"Minimum delay (seconds) [default: 0.01]: ") or "0.01")
    max_delay = float(input(f"Maximum delay (seconds) [default: 2.0]: ") or "2.0")
    stats_interval = float(input(f"Statistics update interval (seconds) [default: 10]: ") or "10")
    verify_ssl = input(f"Verify SSL certificates? (y/n) [default: y]: ").lower() != 'n'
    
    config = {
        'url': url,
        'thread_count': thread_count,
        'base_delay': base_delay,
        'min_delay': min_delay,
        'max_delay': max_delay,
        'timeout': timeout,
        'stats_interval': stats_interval,
        'verify_ssl': verify_ssl
    }
    
    # Display configuration
    print("\n" + "="*80)
    print("📋 CONFIGURATION SUMMARY")
    print("="*80)
    print(f"Target: {url}")
    print(f"Threads: {thread_count}")
    print(f"Base Delay: {base_delay}s")
    print(f"Delay Range: {min_delay}s - {max_delay}s")
    print(f"Timeout: {timeout}s")
    print(f"SSL Verification: {'Enabled' if verify_ssl else 'Disabled'}")
    print(f"Stats Update: Every {stats_interval}s")
    print("\nSiege will stop when server returns: 500, 502, 503, 504 or connection fails")
    print("="*80)
    
    # Confirmation
    confirm = input("\n🚀 Start siege? (y/n): ").lower()
    if confirm != 'y':
        print("Siege cancelled.")
        sys.exit(0)
    
    # Run siege
    tester.run_siege(url, config)
    
    # Save results
    save_results = input("\n💾 Save results to file? (y/n): ").lower() == 'y'
    if save_results:
        filename = input(f"Filename [default: siege_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json]: ").strip()
        tester.save_results(filename if filename else None)

def quick_siege_mode():
    """Quick siege mode with command-line arguments."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="HTTP Siege Mode - Continuous load until critical errors",
        epilog="FOR EDUCATIONAL PURPOSES ONLY"
    )
    
    parser.add_argument('url', help="Target URL to siege")
    parser.add_argument('-t', '--threads', type=int, default=10,
                       help="Number of siege threads (default: 10)")
    parser.add_argument('-d', '--delay', type=float, default=0.05,
                       help="Base delay between requests in seconds (default: 0.05)")
    parser.add_argument('-T', '--timeout', type=int, default=30,
                       help="Request timeout in seconds (default: 30)")
    parser.add_argument('--min-delay', type=float, default=0.01,
                       help="Minimum delay between requests (default: 0.01)")
    parser.add_argument('--max-delay', type=float, default=2.0,
                       help="Maximum delay between requests (default: 2.0)")
    parser.add_argument('--no-ssl-verify', action='store_true',
                       help="Disable SSL certificate verification")
    parser.add_argument('--output', help="Output filename for results")
    
    args = parser.parse_args()
    
    tester = SiegeModeTester()
    
    config = {
        'url': args.url,
        'thread_count': args.threads,
        'base_delay': args.delay,
        'min_delay': args.min_delay,
        'max_delay': args.max_delay,
        'timeout': args.timeout,
        'verify_ssl': not args.no_ssl_verify,
        'stats_interval': 10.0
    }
    
    print(f"\n🚀 Starting quick siege on {args.url}")
    print(f"   Threads: {args.threads}")
    print(f"   Delay: {args.delay}s (range: {args.min_delay}s - {args.max_delay}s)")
    print(f"   SSL Verify: {'Yes' if not args.no_ssl_verify else 'No'}")
    print(f"   Press Ctrl+C to stop manually\n")
    
    tester.run_siege(args.url, config)
    
    if args.output:
        tester.save_results(args.output)
    else:
        save = input("\n💾 Save results to file? (y/n): ").lower() == 'y'
        if save:
            tester.save_results()

def main():
    """Main entry point."""
    print("="*80)
    print("🔥 HTTP SIEGE MODE TESTER")
    print("="*80)
    print("\nChoose mode:")
    print("1. Interactive Mode (Recommended)")
    print("2. Quick Siege Mode (Command-line)")
    print("3. Exit")
    
    choice = input("\nEnter choice (1-3): ").strip()
    
    if choice == '1':
        interactive_mode()
    elif choice == '2':
        quick_siege_mode()
    elif choice == '3':
        print("Exiting...")
        sys.exit(0)
    else:
        print("Invalid choice!")
        sys.exit(1)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Program interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)