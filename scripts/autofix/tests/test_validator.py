"""
Tests for code validator
"""
import unittest
from autofix.validator import validate_python_syntax, validate_code, validate_fix


class TestValidator(unittest.TestCase):
    """Test code validation functions"""
    
    def test_valid_python_syntax(self):
        """Test that valid Python code passes validation"""
        code = "def hello():\n    return 'world'"
        is_valid, error = validate_python_syntax(code)
        self.assertTrue(is_valid)
        self.assertIsNone(error)
    
    def test_invalid_python_syntax(self):
        """Test that invalid Python code fails validation"""
        code = "def hello(\n    return 'world'"  # Missing closing paren
        is_valid, error = validate_python_syntax(code)
        self.assertFalse(is_valid)
        self.assertIsNotNone(error)
        self.assertIn("Syntax error", error)
    
    def test_validate_code_python(self):
        """Test validate_code for Python files"""
        code = "print('hello')"
        is_valid, error = validate_code(code, "test.py")
        self.assertTrue(is_valid)
        self.assertIsNone(error)
    
    def test_validate_code_empty(self):
        """Test that empty code fails validation for non-Python files"""
        is_valid, error = validate_code("", "test.txt")
        self.assertFalse(is_valid)
        self.assertIn("empty", error.lower())
    
    def test_validate_fix_identical(self):
        """Test that identical code fails validation"""
        code = "print('hello')"
        is_valid, error = validate_fix(code, code, "test.py")
        self.assertFalse(is_valid)
        self.assertIn("identical", error.lower())
    
    def test_validate_fix_valid(self):
        """Test that valid fixes pass validation"""
        original = "print('hello')"
        fixed = "print('hello world')"
        is_valid, error = validate_fix(fixed, original, "test.py")
        self.assertTrue(is_valid)
        self.assertIsNone(error)
    
    def test_validate_fix_too_small(self):
        """Test that suspiciously small fixes fail validation"""
        original = "print('hello')\nprint('world')\nprint('test')"
        fixed = "x"  # Way too small
        is_valid, error = validate_fix(fixed, original, "test.py")
        self.assertFalse(is_valid)
        self.assertIn("small", error.lower())


if __name__ == '__main__':
    unittest.main()

