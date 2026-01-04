"""
File Scanner: Discovers and filters files for scanning
"""
import os
from pathlib import Path
from typing import List


def get_repo_root() -> Path:
    """Get the repository root directory
    
    Uses GITHUB_WORKSPACE if available (GitHub Actions), otherwise
    calculates from script location (goes up 3 levels from script dir).
    """
    # In GitHub Actions, GITHUB_WORKSPACE is the repo root
    workspace = os.getenv('GITHUB_WORKSPACE')
    if workspace:
        return Path(workspace)
    
    # Otherwise, calculate from script location
    # Script is at .github/ai-review/scripts/autofix/scanner.py
    # Go up 3 levels to get to repo root
    script_dir = Path(__file__).parent.parent.parent.resolve()
    repo_root = script_dir.parent.parent
    return repo_root


def should_scan_file(file_path: Path) -> bool:
    """Should we scan this file?
    
    Args:
        file_path: Path to the file
        
    Returns:
        True if file should be scanned, False otherwise
    """
    
    skip_dirs = {'node_modules', '.git', 'dist', 'build', '__pycache__', 
                 '.venv', 'venv', 'env', '.pytest_cache', 'htmlcov',
                 'coverage', '.next', 'out', 'target', 'bin', 'obj'}
    
    skip_files = {'.min.js', '.generated.', '.lock', '.min.css', 
                  '.bundle.', '.chunk.'}
    
    # Check directories
    if any(skip_dir in file_path.parts for skip_dir in skip_dirs):
        return False
    
    # Check file patterns
    if any(skip in str(file_path) for skip in skip_files):
        return False
    
    # Skip test files for now (too many potential false positives)
    if 'test' in str(file_path).lower() or 'spec' in str(file_path).lower():
        return False
    
    return True


def discover_files(repo_root: Path, file_patterns: List[str]) -> List[Path]:
    """Discover files matching patterns in the repository
    
    Args:
        repo_root: Repository root directory
        file_patterns: List of file patterns (e.g., ['*.py', '*.js'])
        
    Returns:
        List of file paths to scan
        
    Raises:
        ValueError: If file patterns are invalid or contain malicious content
    """
    # Validate input parameters
    if not isinstance(repo_root, Path):
        raise ValueError("repo_root must be a Path object")
    
    if not isinstance(file_patterns, list):
        raise ValueError("file_patterns must be a list")
    
    if not file_patterns:
        raise ValueError("file_patterns cannot be empty")
    
    # Limit number of patterns to prevent DoS
    MAX_PATTERNS = 20
    if len(file_patterns) > MAX_PATTERNS:
        raise ValueError(f"Too many file patterns (max {MAX_PATTERNS}): {len(file_patterns)}")
    
    # Validate each pattern
    ALLOWED_PATTERN_CHARS = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789*._-/')
    for pattern in file_patterns:
        if not isinstance(pattern, str):
            raise ValueError(f"Invalid pattern type: {type(pattern)}")
        
        if not pattern or len(pattern) > 50:
            raise ValueError(f"Pattern must be 1-50 characters: {pattern}")
        
        # Check for directory traversal
        if '..' in pattern:
            raise ValueError(f"Directory traversal not allowed in pattern: {pattern}")
        
        # Check for absolute paths
        if pattern.startswith('/') or (len(pattern) > 1 and pattern[1] == ':'):
            raise ValueError(f"Absolute paths not allowed in pattern: {pattern}")
        
        # Validate allowed characters
        if not all(c in ALLOWED_PATTERN_CHARS for c in pattern):
            raise ValueError(f"Pattern contains invalid characters: {pattern}")
        
        # Prevent overly broad patterns
        if pattern in ['*', '**', '**/*', '*.*']:
            raise ValueError(f"Pattern too broad (use specific extensions): {pattern}")
    
    files_to_scan = []
    
    # Limit total files discovered
    MAX_FILES = 10000
    
    for pattern in file_patterns:
        try:
            matches = list(repo_root.rglob(pattern))
            files_to_scan.extend([f for f in matches if should_scan_file(f)])
            
            # Check if we've exceeded the limit
            if len(files_to_scan) > MAX_FILES:
                files_to_scan = files_to_scan[:MAX_FILES]
                break
        except (OSError, ValueError) as e:
            # Skip patterns that cause errors
            continue
    
    return files_to_scan


def generate_synthetic_diff(file_path: str, content: str) -> str:
    """Generate a diff for full file as if it were newly added
    
    This allows the review agents to analyze the entire file
    
    Args:
        file_path: Relative path to the file
        content: File content
        
    Returns:
        Synthetic diff string
    """
    lines = content.split('\n')
    
    # Limit to first 500 lines to avoid token limits
    lines_to_include = lines[:500]
    
    diff_lines = [
        f"diff --git a/{file_path} b/{file_path}",
        "--- /dev/null",
        f"+++ b/{file_path}",
        f"@@ -0,0 +1,{len(lines_to_include)} @@"
    ]
    
    # Add lines with + prefix
    diff_lines.extend([f"+{line}" for line in lines_to_include])
    
    if len(lines) > 500:
        diff_lines.append("+... (truncated)")
    
    return '\n'.join(diff_lines)

