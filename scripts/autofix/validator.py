"""
Code Validator: Validates AI-generated code before applying
"""
import ast
import sys
from pathlib import Path
from typing import Tuple, Optional


class CodeValidationError(Exception):
    """Raised when code validation fails"""
    pass


def validate_python_syntax(code: str, file_path: str = None) -> Tuple[bool, Optional[str]]:
    """Validate Python syntax
    
    Args:
        code: Python code to validate
        file_path: Optional file path for error messages
        
    Returns:
        tuple: (is_valid, error_message)
    """
    try:
        ast.parse(code)
        return True, None
    except SyntaxError as e:
        error_msg = f"Syntax error at line {e.lineno}: {e.msg}"
        if file_path:
            error_msg = f"{file_path}: {error_msg}"
        return False, error_msg
    except Exception as e:
        error_msg = f"Validation error: {str(e)}"
        if file_path:
            error_msg = f"{file_path}: {error_msg}"
        return False, error_msg


def validate_code(code: str, file_path: str) -> Tuple[bool, Optional[str]]:
    """Validate code based on file extension
    
    Args:
        code: Code content to validate
        file_path: Path to the file
        
    Returns:
        tuple: (is_valid, error_message)
    """
    path = Path(file_path)
    extension = path.suffix.lower()
    
    if extension == '.py':
        return validate_python_syntax(code, file_path)
    
    # For other file types, we can add validators later
    # For now, just check that code is not empty
    if not code or not code.strip():
        return False, f"{file_path}: Generated code is empty or whitespace only"
    
    # Basic sanity check: code should have reasonable length
    if len(code.strip()) < 10:
        return False, f"{file_path}: Generated code is suspiciously short"
    
    # If we can't validate, at least check it's not obviously broken
    # (e.g., contains only whitespace or error messages)
    if code.strip().lower().startswith(('error', 'exception', 'failed', 'cannot')):
        return False, f"{file_path}: Generated code appears to contain error messages"
    
    return True, None


def validate_fix(fixed_code: str, original_code: str, file_path: str) -> Tuple[bool, Optional[str]]:
    """Validate a generated fix
    
    Performs multiple checks:
    1. Syntax validation (if applicable)
    2. Basic sanity checks
    3. Ensures fix is not identical to original (would be pointless)
    
    Args:
        fixed_code: The generated fixed code
        original_code: The original code
        file_path: Path to the file
        
    Returns:
        tuple: (is_valid, error_message)
    """
    # Check 1: Not empty
    if not fixed_code or not fixed_code.strip():
        return False, f"{file_path}: Generated fix is empty"
    
    # Check 2: Not identical to original (would be pointless)
    if fixed_code.strip() == original_code.strip():
        return False, f"{file_path}: Generated fix is identical to original code"
    
    # Check 3: Syntax validation
    is_valid, error = validate_code(fixed_code, file_path)
    if not is_valid:
        return False, error
    
    # Check 4: Reasonable size (not too small or too large)
    size_ratio = len(fixed_code) / len(original_code) if original_code else 1.0
    if size_ratio < 0.1:
        return False, f"{file_path}: Generated fix is suspiciously small ({size_ratio:.1%} of original)"
    if size_ratio > 5.0:
        return False, f"{file_path}: Generated fix is suspiciously large ({size_ratio:.1%} of original)"
    
    return True, None

