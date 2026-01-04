"""
Code Fix Generator: Generates code fixes using LLM
"""
import os
import threading
from typing import Optional, Dict, Callable, Any
from common.model_manager import ModelManager
from autofix.validator import validate_fix, CodeValidationError

# Timeout for LLM calls (180 seconds default - increased for complex fixes)
LLM_TIMEOUT_SECONDS = int(os.getenv('LLM_TIMEOUT_SECONDS', '180'))


class TimeoutError(Exception):
    """Raised when an operation times out"""
    pass


def with_timeout(func: Callable, timeout_seconds: int, *args, **kwargs) -> Any:
    """Execute a function with a timeout
    
    Args:
        func: Function to execute
        timeout_seconds: Timeout in seconds
        *args, **kwargs: Arguments to pass to func
        
    Returns:
        Result of func
        
    Raises:
        TimeoutError: If function doesn't complete within timeout
    """
    result = [None]
    exception = [None]
    
    def target():
        try:
            result[0] = func(*args, **kwargs)
        except Exception as e:
            exception[0] = e
    
    thread = threading.Thread(target=target)
    thread.daemon = True
    thread.start()
    thread.join(timeout=timeout_seconds)
    
    if thread.is_alive():
        raise TimeoutError(f"Operation timed out after {timeout_seconds} seconds")
    
    if exception[0]:
        raise exception[0]
    
    return result[0]


class CodeFixGenerator:
    """Generates code fixes using LLM"""
    
    def __init__(self, model_manager: ModelManager):
        self.model_manager = model_manager
    
    def generate_fix(self, file_path: str, issue: Dict, file_content: str) -> Optional[str]:
        """Generate a fix for the issue
        
        Args:
            file_path: Path to file
            issue: Issue dict with description, severity, line_number, suggestion
            file_content: Current file content
            
        Returns:
            Fixed file content or None if fix failed
        """
        
        prompt = f"""You are a code fixing assistant. Generate a fix for this issue:

**File:** {file_path}
**Issue:** {issue['description']}
**Severity:** {issue['severity']}
**Line:** {issue.get('line_number', 'unknown')}
**Suggestion:** {issue.get('suggestion', 'N/A')}

**Current Code:**
```
{file_content[:5000]}
```

**Instructions:**
1. Generate the COMPLETE fixed file content
2. Only fix the specific issue mentioned
3. Keep all other code exactly unchanged
4. Ensure the fix is minimal and safe
5. Maintain the same file structure and formatting
6. Do NOT add explanations or comments about the fix

Return ONLY the complete file content with the fix applied, nothing else.
"""
        
        system_prompt = "You are a precise code fixing assistant. Return only the fixed code, no explanations or markdown formatting."
        
        try:
            # Wrap LLM call with timeout to prevent indefinite hangs
            response, model_used = with_timeout(
                lambda: self.model_manager.generate_with_fallback(
                    ['glm_4_7', 'claude_sonnet', 'openai_gpt4'],
                    prompt,
                    system_prompt
                ),
                LLM_TIMEOUT_SECONDS
            )
            
            # Extract code from response (handle markdown code blocks)
            fixed_code = self._extract_code(response)
            
            # Validate the generated code before accepting it
            is_valid, error_msg = validate_fix(fixed_code, file_content, file_path)
            if not is_valid:
                print(f"  ❌ Code validation failed: {error_msg}")
                return None
            
            print(f"  ✓ Code validation passed")
            return fixed_code
            
        except TimeoutError as e:
            print(f"  ⚠️  LLM call timed out after {LLM_TIMEOUT_SECONDS}s: {e}")
            return None
        except Exception as e:
            print(f"  ⚠️  Failed to generate fix: {e}")
            return None
    
    def _extract_code(self, response: str) -> str:
        """Extract code from LLM response, handling markdown blocks"""
        # Remove markdown code blocks if present
        lines = response.split('\n')
        code_lines = []
        in_code_block = False
        skipping_intro = True
        
        for line in lines:
            # Check for code block markers
            if line.strip().startswith('```'):
                in_code_block = not in_code_block
                skipping_intro = False
                continue
            
            # Skip intro text before code
            if skipping_intro and (line.strip().startswith('#') or 
                                   line.strip().startswith('**') or
                                   'here' in line.lower()[:10] or
                                   'fixed' in line.lower()[:20]):
                continue
            
            skipping_intro = False
            
            # Add code lines
            if in_code_block or (not line.strip().startswith('#') and 
                                  not line.strip().startswith('**')):
                code_lines.append(line)
        
        return '\n'.join(code_lines).strip()

