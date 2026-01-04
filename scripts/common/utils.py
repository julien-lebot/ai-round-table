#!/usr/bin/env python3
"""
Utility functions for AI code review system
"""
import re

# Pre-compiled regex for sanitizing error messages (remove sensitive info)
_ERROR_SANITIZE_PATTERNS = [
    re.compile(r'(api[_-]?key|token|authorization|bearer|secret|password|credential)\s*[:=]\s*["\']?[^\s"\']+', re.IGNORECASE),
    re.compile(r'sk-[a-zA-Z0-9]{20,}', re.IGNORECASE),  # OpenAI/Anthropic keys
    re.compile(r'ghp_[a-zA-Z0-9]{36}', re.IGNORECASE),  # GitHub tokens
    re.compile(r'Bearer\s+[^\s]+', re.IGNORECASE),
]


def sanitize_error_message(error_msg: str) -> str:
    """
    Sanitize error messages to prevent leaking API keys, tokens, or sensitive info.
    """
    if not error_msg:
        return ""
    
    sanitized = error_msg
    for pattern in _ERROR_SANITIZE_PATTERNS:
        sanitized = pattern.sub(r'[REDACTED]', sanitized)
    
    return sanitized

