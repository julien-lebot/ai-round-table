"""
AutoFix Scanner: Scans code files for fixable issues
Completely independent of PR review system
"""
import json
import fnmatch
import os
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from common.types import ReviewIssue, AgentReview, IssueSeverity
from common.model_manager import ModelManager

# Configure logging
logger = logging.getLogger(__name__)


class AutoFixScanner:
    """Scanner for finding auto-fixable issues in code"""
    
    def __init__(self, focus_area: str, agent_config: Dict[str, Any], model_manager: ModelManager, 
                 settings: Dict[str, Any] = None, datetime_provider: Optional[Callable[[], datetime]] = None,
                 repo_root: Optional[Path] = None):
        """
        Args:
            focus_area: The focus area (style, security, performance, etc.)
            agent_config: Agent configuration from agents.yaml
            model_manager: Model manager for API calls
            settings: Settings from agents.yaml (autofix section)
            datetime_provider: Function that returns current datetime (for testing)
            repo_root: Repository root path for path validation (default: auto-detect)
        """
        self.focus_area = focus_area
        self.name = agent_config['name']
        self.system_prompt = agent_config['system_prompt']
        self.models = agent_config['models']
        self.model_manager = model_manager
        self.datetime_provider = datetime_provider or (lambda: datetime.utcnow())
        
        # Set repository root for path validation
        if repo_root is None:
            # Auto-detect from GITHUB_WORKSPACE or current directory
            workspace = os.getenv('GITHUB_WORKSPACE')
            self.repo_root = Path(workspace).resolve() if workspace else Path.cwd().resolve()
        else:
            self.repo_root = Path(repo_root).resolve()
        
        # Get autofix settings from config
        autofix_settings = settings.get('autofix', {}) if settings else {}
        self.skip_patterns = autofix_settings.get('skip_files', [])
        self.max_llm_size = autofix_settings.get('max_llm_scan_size', 20000)  # 20KB default
    
    def should_skip_file(self, file_path: str) -> bool:
        """Check if file should be skipped based on patterns
        
        Args:
            file_path: Path to the file to check (relative or absolute)
            
        Returns:
            True if file should be skipped, False otherwise
            
        Raises:
            ValueError: If file_path contains directory traversal attempts or escapes repository
        """
        # Normalize and validate file path to prevent directory traversal
        try:
            # Convert to Path object
            path_obj = Path(file_path)
            
            # Immediately reject paths with directory traversal patterns
            if '..' in path_obj.parts:
                raise ValueError(f"Path traversal detected in file path: {file_path}")
            
            # If path is absolute, validate it's within the repository
            if path_obj.is_absolute():
                # Resolve the path (without following symlinks for security)
                try:
                    resolved_path = path_obj.resolve()
                    # Check if the resolved path is within repository boundaries
                    # Use is_relative_to() for Python 3.9+, fallback for older versions
                    try:
                        # Python 3.9+
                        if not resolved_path.is_relative_to(self.repo_root):
                            raise ValueError(f"Absolute path escapes repository: {file_path}")
                    except AttributeError:
                        # Python 3.8 fallback
                        try:
                            resolved_path.relative_to(self.repo_root)
                        except ValueError:
                            raise ValueError(f"Absolute path escapes repository: {file_path}")
                except (OSError, RuntimeError) as e:
                    # Path doesn't exist or other OS error
                    raise ValueError(f"Invalid absolute path: {file_path} - {str(e)}")
            else:
                # For relative paths, construct the full path and validate
                # This prevents paths like "../../etc/passwd" from escaping
                try:
                    full_path = (self.repo_root / path_obj).resolve()
                    # Verify the resolved path is still within repository
                    try:
                        # Python 3.9+
                        if not full_path.is_relative_to(self.repo_root):
                            raise ValueError(f"Relative path escapes repository: {file_path}")
                    except AttributeError:
                        # Python 3.8 fallback
                        try:
                            full_path.relative_to(self.repo_root)
                        except ValueError:
                            raise ValueError(f"Relative path escapes repository: {file_path}")
                except (OSError, RuntimeError) as e:
                    # Path resolution failed
                    raise ValueError(f"Invalid relative path: {file_path} - {str(e)}")
            
            # Path is valid, now check against skip patterns using normalized path
            normalized = str(path_obj.as_posix())
            for pattern in self.skip_patterns:
                if fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(file_path, pattern):
                    return True
            
            return False
        except ValueError:
            # Re-raise ValueError as-is (these are our validation errors)
            raise
        except Exception as e:
            # Catch any other unexpected errors and wrap them
            raise ValueError(f"Invalid file path: {file_path} - {type(e).__name__}: {str(e)}")
    
    def scan_file(self, file_path: str, content: str) -> AgentReview:
        """Scan a file for auto-fixable issues
        
        Args:
            file_path: Path to the file
            content: File content
            
        Returns:
            AgentReview with found issues
        """
        # Check exclusion list
        if self.should_skip_file(file_path):
            return AgentReview(
                agent_name=self.name,
                agent_role='autofix_scanner',
                issues=[],
                summary=f"Skipped: File in exclusion list",
                model_used="none",
                timestamp=self.datetime_provider().isoformat() + 'Z'
            )
        
        # Use quick static analysis for large files, LLM for small files
        if len(content) > self.max_llm_size:
            # For large files, use rule-based scanning only (no LLM cost)
            issues = self._quick_static_scan(file_path, content)
            return AgentReview(
                agent_name=self.name,
                agent_role='autofix_scanner',
                issues=issues,
                summary=f"Found {len(issues)} issue(s) via static analysis ({len(content)} bytes > {self.max_llm_size} limit)",
                model_used="static",
                timestamp=self.datetime_provider().isoformat() + 'Z'
            )
        
        # For small files, use LLM but with optimized prompt
        prompt = self._build_autofix_prompt(file_path, content)
        
        try:
            response, model_used = self.model_manager.generate_with_fallback(
                self.models,
                prompt,
                self.system_prompt
            )
            
            issues = self._parse_response(response)
            
            return AgentReview(
                agent_name=self.name,
                agent_role='autofix_scanner',
                issues=issues,
                summary=f"Found {len(issues)} fixable issue(s)",
                model_used=model_used,
                timestamp=self.datetime_provider().isoformat() + 'Z'
            )
        except Exception as e:
            logger.error(f"Scanner error for {file_path}: {str(e)}")
            return AgentReview(
                agent_name=self.name,
                agent_role='autofix_scanner',
                issues=[],
                summary=f"Scanner error: {str(e)[:100]}",
                model_used="none",
                timestamp=self.datetime_provider().isoformat() + 'Z'
            )
    
    def _quick_static_scan(self, file_path: str, content: str) -> List[ReviewIssue]:
        """Quick rule-based scanning without LLM - for large files"""
        issues = []
        lines = content.split('\n')
        
        # Rule 1: Long lines
        for i, line in enumerate(lines, 1):
            if len(line) > 120:
                issues.append(ReviewIssue(
                    severity=IssueSeverity.LOW,
                    category="line length",
                    description=f"Line exceeds 120 characters ({len(line)} chars)",
                    line_number=i,
                    file_path=file_path
                ))
                if len(issues) >= 5:  # Max 5 issues per file
                    break
        
        # Rule 2: Commented-out code (common patterns)
        if len(issues) < 5:
            in_comment_block = False
            comment_start = 0
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                # Detect comment blocks
                if '/*' in stripped or '///' in stripped or '"""' in stripped:
                    if not in_comment_block:
                        in_comment_block = True
                        comment_start = i
                elif in_comment_block and ('*/' in stripped or '"""' in stripped):
                    in_comment_block = False
                    if i - comment_start > 5:  # Large comment block
                        issues.append(ReviewIssue(
                            severity=IssueSeverity.LOW,
                            category="dead code",
                            description=f"Large commented block ({i - comment_start} lines) - may be dead code",
                            line_number=comment_start,
                            file_path=file_path
                        ))
                        if len(issues) >= 5:
                            break
        
        return issues[:5]  # Max 5 issues
    
    def _build_autofix_prompt(self, file_path: str, content: str) -> str:
        """Build autofix-specific prompt"""
        
        # Count lines for context
        line_count = content.count('\n') + 1
        
        return f"""# AutoFix Bot - Quick Scan for Tedious Fixes

File: `{file_path}` ({line_count} lines)
Focus: **{self.focus_area}**

```
{content}
```

## Task: Find 1-3 OBVIOUS mechanical fixes

Scan QUICKLY for boring, tedious issues that:
- Are 100% safe to auto-fix
- Won't break anything
- Are in the **{self.focus_area}** category

**Focus on these common issues:**
- Unused imports/variables
- Missing documentation
- Inconsistent formatting
- Dead/commented code
- Long lines (>120 chars)
- Exception handling issues
- Error handling improvements

**IMPORTANT:**
- Scan fast, don't analyze deeply
- Max 3 issues per file
- Only report MEDIUM or LOW severity
- Include line numbers if possible

Return JSON:
{{
  "issues": [
    {{
      "severity": "MEDIUM",
      "category": "style",
      "description": "Brief description",
      "line_number": 42
    }}
  ]
}}

If no obvious issues, return: {{"issues": []}}

❌ **DON'T fix these:**
- Complex architectural issues
- Anything requiring business logic knowledge
- Subjective style preferences
- Breaking changes

**Output Format:**

{{
    "issues": [
        {{
            "severity": "HIGH|MEDIUM",
            "category": "Brief category",
            "description": "What's wrong (be specific with line numbers if relevant)",
            "line_number": 42,
            "suggestion": "How to fix it (be specific)"
        }}
    ]
}}

Be specific about fixes. Humans will review your PR before merging.
"""
    
    def _parse_response(self, response: str) -> List[ReviewIssue]:
        """Parse scanner response into ReviewIssue objects with validation
        
        Args:
            response: LLM response string containing JSON
            
        Returns:
            List of validated ReviewIssue objects (empty list if no issues or parsing error)
        """
        try:
            # Extract JSON from response
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            
            if json_start < 0 or json_end <= json_start:
                logger.warning("No JSON found in LLM response")
                return []
            
            json_str = response[json_start:json_end]
            
            # Validate JSON size to prevent DoS
            MAX_JSON_SIZE = 100000  # 100KB max
            if len(json_str) > MAX_JSON_SIZE:
                logger.error(f"Response JSON too large: {len(json_str)} bytes (max {MAX_JSON_SIZE})")
                raise ValueError(f"Response JSON too large: {len(json_str)} bytes")
            
            data = json.loads(json_str)
            
            # Validate top-level structure
            if not isinstance(data, dict):
                logger.error("Response is not a JSON object")
                raise ValueError("Response must be a JSON object")
            
            if 'issues' not in data:
                logger.debug("No 'issues' field in response (valid empty result)")
                return []
            
            if not isinstance(data['issues'], list):
                logger.error("'issues' field is not an array")
                raise ValueError("'issues' field must be an array")
            
            # Limit number of issues to prevent DoS
            MAX_ISSUES = 50
            if len(data['issues']) > MAX_ISSUES:
                data['issues'] = data['issues'][:MAX_ISSUES]
            
            issues = []
            for idx, issue_dict in enumerate(data['issues']):
                # Validate issue structure
                if not isinstance(issue_dict, dict):
                    continue  # Skip invalid issues
                
                # Validate and sanitize fields
                severity_str = issue_dict.get('severity', 'MEDIUM')
                if not isinstance(severity_str, str) or severity_str not in ['HIGH', 'MEDIUM', 'LOW']:
                    continue  # Skip invalid severities
                
                category = issue_dict.get('category', 'General')
                if not isinstance(category, str) or len(category) > 100:
                    category = 'General'
                
                description = issue_dict.get('description', '')
                if not isinstance(description, str) or len(description) > 1000:
                    continue  # Skip issues with invalid or too long descriptions
                
                suggestion = issue_dict.get('suggestion')
                if suggestion is not None:
                    if not isinstance(suggestion, str) or len(suggestion) > 2000:
                        suggestion = None  # Ignore invalid suggestions
                
                line_number = issue_dict.get('line_number')
                if line_number is not None:
                    if not isinstance(line_number, int) or line_number < 0 or line_number > 1000000:
                        line_number = None  # Ignore invalid line numbers
                
                code_snippet = issue_dict.get('code_snippet')
                if code_snippet is not None:
                    if not isinstance(code_snippet, str) or len(code_snippet) > 5000:
                        code_snippet = None  # Ignore invalid code snippets
                
                try:
                    issues.append(ReviewIssue(
                        severity=IssueSeverity[severity_str],
                        category=category,
                        description=description,
                        file_path=None,  # Will be set by caller
                        line_number=line_number,
                        suggestion=suggestion,
                        code_snippet=code_snippet
                    ))
                except (KeyError, ValueError):
                    # Skip invalid issues
                    continue
            
            logger.debug(f"Successfully parsed {len(issues)} issue(s) from LLM response")
            return issues
        except json.JSONDecodeError as e:
            # JSON parsing failed - log and return empty to degrade gracefully
            logger.warning(f"Failed to parse JSON from LLM response: {str(e)[:100]}")
            return []
        except (KeyError, TypeError, ValueError) as e:
            # Validation error - log and return empty to degrade gracefully
            logger.warning(f"Invalid response structure from LLM: {str(e)[:100]}")
            return []
        except Exception as e:
            # Unexpected error - log and return empty to degrade gracefully
            logger.error(f"Unexpected error parsing LLM response: {type(e).__name__}: {str(e)[:100]}")
            return []

