"""
Rate Limiter: Prevents GitHub API quota exhaustion
"""
import time
from typing import Optional
from threading import Lock


class RateLimiter:
    """Simple rate limiter for API calls"""
    
    def __init__(self, max_calls: int = 5000, time_window: int = 3600):
        """Initialize rate limiter
        
        Args:
            max_calls: Maximum number of calls allowed
            time_window: Time window in seconds (default: 1 hour)
        """
        self.max_calls = max_calls
        self.time_window = time_window
        self.calls = []
        self.lock = Lock()
    
    def wait_if_needed(self) -> None:
        """Wait if rate limit would be exceeded
        
        GitHub API allows 5000 requests per hour for authenticated requests.
        This ensures we don't exceed that limit.
        """
        with self.lock:
            now = time.time()
            
            # Remove calls outside the time window
            self.calls = [call_time for call_time in self.calls 
                         if now - call_time < self.time_window]
            
            # If we're at the limit, wait until the oldest call expires
            if len(self.calls) >= self.max_calls:
                oldest_call = min(self.calls)
                wait_time = self.time_window - (now - oldest_call) + 1
                if wait_time > 0:
                    print(f"  ⏳ Rate limit reached, waiting {wait_time:.1f}s...")
                    time.sleep(wait_time)
                    # Clean up again after waiting
                    now = time.time()
                    self.calls = [call_time for call_time in self.calls 
                                 if now - call_time < self.time_window]
            
            # Record this call
            self.calls.append(now)
    
    def get_remaining_calls(self) -> int:
        """Get remaining calls in current window"""
        with self.lock:
            now = time.time()
            self.calls = [call_time for call_time in self.calls 
                         if now - call_time < self.time_window]
            return max(0, self.max_calls - len(self.calls))


# Global rate limiter instance
# GitHub allows 5000 requests/hour for authenticated requests
# We'll be conservative and use 4500 to leave buffer
_global_rate_limiter = RateLimiter(max_calls=4500, time_window=3600)


def rate_limit_github_api() -> None:
    """Rate limit GitHub API calls using global limiter"""
    _global_rate_limiter.wait_if_needed()


def get_remaining_api_calls() -> int:
    """Get remaining GitHub API calls in current window"""
    return _global_rate_limiter.get_remaining_calls()

