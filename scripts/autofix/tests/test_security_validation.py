"""
Tests for security validation and malicious input handling
Tests path traversal, code injection, and DoS prevention
"""
import pytest
from pathlib import Path
import sys
import tempfile
import shutil

# Add scripts directory to path
scripts_dir = Path(__file__).parent.parent.parent
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from autofix.autofix_scanner import AutoFixScanner
from autofix.scanner import discover_files
from common.model_manager import ModelManager
from unittest.mock import Mock, patch


class TestPathTraversalProtection:
    """Test protection against directory traversal attacks"""
    
    def setup_method(self):
        """Set up test fixtures"""
        # Create a temporary directory to use as repo root
        self.test_dir = tempfile.mkdtemp()
        self.repo_root = Path(self.test_dir)
        
    def teardown_method(self):
        """Clean up test fixtures"""
        if self.test_dir:
            shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def test_file_path_with_parent_directory_rejected(self):
        """Test that paths with .. are rejected"""
        agent_config = {
            'name': 'Test Agent',
            'system_prompt': 'test',
            'models': ['test_model']
        }
        
        mock_manager = Mock(spec=ModelManager)
        scanner = AutoFixScanner('style', agent_config, mock_manager, repo_root=self.repo_root)
        
        # Path with directory traversal
        with pytest.raises(ValueError) as exc_info:
            scanner.should_skip_file('../../../etc/passwd')
        
        assert "Path traversal detected" in str(exc_info.value)
    
    def test_absolute_path_outside_repo_rejected(self):
        """Test that absolute paths outside repository are rejected"""
        agent_config = {
            'name': 'Test Agent',
            'system_prompt': 'test',
            'models': ['test_model']
        }
        
        mock_manager = Mock(spec=ModelManager)
        scanner = AutoFixScanner('style', agent_config, mock_manager, repo_root=self.repo_root)
        
        # Absolute path outside repository
        with pytest.raises(ValueError) as exc_info:
            scanner.should_skip_file('/etc/passwd')
        
        assert "escapes repository" in str(exc_info.value)
    
    def test_windows_absolute_path_outside_repo_rejected(self):
        """Test that Windows absolute paths outside repository are rejected"""
        agent_config = {
            'name': 'Test Agent',
            'system_prompt': 'test',
            'models': ['test_model']
        }
        
        mock_manager = Mock(spec=ModelManager)
        scanner = AutoFixScanner('style', agent_config, mock_manager, repo_root=self.repo_root)
        
        # Windows absolute path
        with pytest.raises(ValueError) as exc_info:
            scanner.should_skip_file('C:/Windows/System32/config/sam')
        
        assert "escapes repository" in str(exc_info.value)
    
    def test_relative_path_escaping_repo_rejected(self):
        """Test that relative paths escaping repository are rejected"""
        agent_config = {
            'name': 'Test Agent',
            'system_prompt': 'test',
            'models': ['test_model']
        }
        
        mock_manager = Mock(spec=ModelManager)
        # Create repo at /tmp/test_repo
        scanner = AutoFixScanner('style', agent_config, mock_manager, repo_root=self.repo_root)
        
        # Try to escape with relative path
        with pytest.raises(ValueError) as exc_info:
            scanner.should_skip_file('../../etc/passwd')
        
        assert "Path traversal detected" in str(exc_info.value)
    
    def test_absolute_path_within_repo_allowed(self):
        """Test that absolute paths within repository are allowed"""
        agent_config = {
            'name': 'Test Agent',
            'system_prompt': 'test',
            'models': ['test_model']
        }
        
        mock_manager = Mock(spec=ModelManager)
        scanner = AutoFixScanner('style', agent_config, mock_manager, repo_root=self.repo_root)
        
        # Create a file within the repo
        test_file = self.repo_root / 'test.py'
        test_file.touch()
        
        # Absolute path within repository should be allowed (not skipped for path reasons)
        # It may still be skipped if it matches skip patterns
        result = scanner.should_skip_file(str(test_file))
        
        # Should return boolean, not raise exception
        assert isinstance(result, bool)
    
    def test_valid_relative_path_allowed(self):
        """Test that valid relative paths within repository are allowed"""
        agent_config = {
            'name': 'Test Agent',
            'system_prompt': 'test',
            'models': ['test_model']
        }
        
        mock_manager = Mock(spec=ModelManager)
        scanner = AutoFixScanner('style', agent_config, mock_manager, repo_root=self.repo_root)
        
        # Create a subdirectory and file
        subdir = self.repo_root / 'src'
        subdir.mkdir()
        test_file = subdir / 'main.py'
        test_file.touch()
        
        # Valid relative path
        result = scanner.should_skip_file('src/main.py')
        
        # Should return boolean, not raise exception
        assert isinstance(result, bool)
    
    def test_symlink_escaping_repo_rejected(self):
        """Test that symlinks pointing outside repository are rejected"""
        agent_config = {
            'name': 'Test Agent',
            'system_prompt': 'test',
            'models': ['test_model']
        }
        
        mock_manager = Mock(spec=ModelManager)
        scanner = AutoFixScanner('style', agent_config, mock_manager, repo_root=self.repo_root)
        
        # Create a symlink pointing outside repo (if OS supports it)
        try:
            link_path = self.repo_root / 'evil_link'
            link_path.symlink_to('/etc/passwd')
            
            # Should be rejected when resolved
            with pytest.raises(ValueError) as exc_info:
                scanner.should_skip_file(str(link_path))
            
            assert "escapes repository" in str(exc_info.value) or "Invalid" in str(exc_info.value)
        except (OSError, NotImplementedError):
            # Skip test if OS doesn't support symlinks
            pytest.skip("OS doesn't support symlinks")


class TestFilePatternValidation:
    """Test validation of file patterns to prevent DoS"""
    
    def test_empty_file_patterns_rejected(self):
        """Test that empty file patterns list is rejected"""
        with pytest.raises(ValueError) as exc_info:
            discover_files(Path('.'), [])
        
        assert "cannot be empty" in str(exc_info.value)
    
    def test_too_many_patterns_rejected(self):
        """Test that excessive file patterns are rejected"""
        patterns = [f'*.py{i}' for i in range(25)]  # More than MAX_PATTERNS (20)
        
        with pytest.raises(ValueError) as exc_info:
            discover_files(Path('.'), patterns)
        
        assert "Too many file patterns" in str(exc_info.value)
    
    def test_directory_traversal_in_pattern_rejected(self):
        """Test that patterns with .. are rejected"""
        with pytest.raises(ValueError) as exc_info:
            discover_files(Path('.'), ['../**/*.py'])
        
        assert "Directory traversal not allowed" in str(exc_info.value)
    
    def test_overly_broad_pattern_rejected(self):
        """Test that overly broad patterns like * are rejected"""
        with pytest.raises(ValueError) as exc_info:
            discover_files(Path('.'), ['*'])
        
        assert "Pattern too broad" in str(exc_info.value)
    
    def test_pattern_with_invalid_characters_rejected(self):
        """Test that patterns with invalid characters are rejected"""
        with pytest.raises(ValueError) as exc_info:
            discover_files(Path('.'), ['*.py; rm -rf /'])
        
        assert "invalid characters" in str(exc_info.value)
    
    def test_absolute_path_pattern_rejected(self):
        """Test that absolute path patterns are rejected"""
        with pytest.raises(ValueError) as exc_info:
            discover_files(Path('.'), ['/etc/*.conf'])
        
        assert "Absolute paths not allowed" in str(exc_info.value)


class TestLLMResponseValidation:
    """Test validation of LLM responses to prevent injection"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.test_dir = tempfile.mkdtemp()
        self.repo_root = Path(self.test_dir)
    
    def teardown_method(self):
        """Clean up test fixtures"""
        if self.test_dir:
            shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def test_oversized_json_response_rejected(self):
        """Test that extremely large JSON responses are rejected"""
        agent_config = {
            'name': 'Test Agent',
            'system_prompt': 'test',
            'models': ['test_model']
        }
        
        mock_manager = Mock(spec=ModelManager)
        scanner = AutoFixScanner('style', agent_config, mock_manager, repo_root=self.repo_root)
        
        # Create a huge JSON response (>100KB)
        huge_json = '{"issues": [' + ','.join([
            '{"severity": "MEDIUM", "category": "test", "description": "x" * 1000}'
            for _ in range(200)
        ]) + ']}'
        
        issues = scanner._parse_response(huge_json)
        
        # Should be rejected or truncated
        assert len(issues) <= 50  # MAX_ISSUES limit
    
    def test_excessive_issues_count_limited(self):
        """Test that excessive number of issues is limited"""
        agent_config = {
            'name': 'Test Agent',
            'system_prompt': 'test',
            'models': ['test_model']
        }
        
        mock_manager = Mock(spec=ModelManager)
        scanner = AutoFixScanner('style', agent_config, mock_manager, repo_root=self.repo_root)
        
        # Create response with 100 issues
        json_response = '{"issues": [' + ','.join([
            '{"severity": "MEDIUM", "category": "test", "description": "Issue %d"}' % i
            for i in range(100)
        ]) + ']}'
        
        issues = scanner._parse_response(json_response)
        
        # Should be limited to MAX_ISSUES (50)
        assert len(issues) <= 50
    
    def test_malformed_json_handled_gracefully(self):
        """Test that malformed JSON doesn't crash"""
        agent_config = {
            'name': 'Test Agent',
            'system_prompt': 'test',
            'models': ['test_model']
        }
        
        mock_manager = Mock(spec=ModelManager)
        scanner = AutoFixScanner('style', agent_config, mock_manager, repo_root=self.repo_root)
        
        # Various malformed inputs
        malformed_inputs = [
            "not json at all",
            "{incomplete",
            '{"issues": "not an array"}',
            '{"issues": [{"severity": "INVALID"}]}',
            '',
            None,
        ]
        
        for bad_input in malformed_inputs:
            if bad_input is None:
                bad_input = ""
            issues = scanner._parse_response(bad_input)
            assert issues == []  # Should return empty list, not crash
    
    def test_field_length_limits_enforced(self):
        """Test that field length limits are enforced"""
        agent_config = {
            'name': 'Test Agent',
            'system_prompt': 'test',
            'models': ['test_model']
        }
        
        mock_manager = Mock(spec=ModelManager)
        scanner = AutoFixScanner('style', agent_config, mock_manager, repo_root=self.repo_root)
        
        # Issue with overly long description
        json_response = '''{
            "issues": [{
                "severity": "MEDIUM",
                "category": "''' + 'x' * 200 + '''",
                "description": "''' + 'y' * 2000 + '''",
                "suggestion": "''' + 'z' * 3000 + '''"
            }]
        }'''
        
        issues = scanner._parse_response(json_response)
        
        # Should handle gracefully - either skip issue or truncate fields
        if issues:
            assert len(issues[0].description) <= 1000
    
    def test_invalid_line_numbers_ignored(self):
        """Test that invalid line numbers are ignored"""
        agent_config = {
            'name': 'Test Agent',
            'system_prompt': 'test',
            'models': ['test_model']
        }
        
        mock_manager = Mock(spec=ModelManager)
        scanner = AutoFixScanner('style', agent_config, mock_manager, repo_root=self.repo_root)
        
        # Issue with invalid line number
        json_response = '''{
            "issues": [{
                "severity": "MEDIUM",
                "category": "test",
                "description": "Test issue",
                "line_number": -5
            }]
        }'''
        
        issues = scanner._parse_response(json_response)
        
        if issues:
            assert issues[0].line_number is None  # Should be ignored
    
    def test_non_string_fields_rejected(self):
        """Test that non-string values in string fields are rejected"""
        agent_config = {
            'name': 'Test Agent',
            'system_prompt': 'test',
            'models': ['test_model']
        }
        
        mock_manager = Mock(spec=ModelManager)
        scanner = AutoFixScanner('style', agent_config, mock_manager, repo_root=self.repo_root)
        
        # Issue with non-string description
        json_response = '''{
            "issues": [{
                "severity": "MEDIUM",
                "category": 12345,
                "description": ["array", "not", "string"]
            }]
        }'''
        
        issues = scanner._parse_response(json_response)
        
        # Should skip invalid issues
        assert len(issues) == 0


class TestInputValidation:
    """Test input validation for scan_and_fix function"""
    
    def test_invalid_focus_area_rejected(self):
        """Test that invalid focus areas are rejected"""
        from autofix.engine import scan_and_fix
        
        with pytest.raises(ValueError) as exc_info:
            scan_and_fix('invalid_area', 1, ['*.py'])
        
        assert "focus_area must be one of" in str(exc_info.value)
    
    def test_invalid_max_prs_rejected(self):
        """Test that invalid max_prs values are rejected"""
        from autofix.engine import scan_and_fix
        
        # Too low
        with pytest.raises(ValueError) as exc_info:
            scan_and_fix('style', 0, ['*.py'])
        assert "between 1 and 50" in str(exc_info.value)
        
        # Too high
        with pytest.raises(ValueError) as exc_info:
            scan_and_fix('style', 100, ['*.py'])
        assert "between 1 and 50" in str(exc_info.value)
    
    def test_non_list_file_patterns_rejected(self):
        """Test that non-list file_patterns are rejected"""
        from autofix.engine import scan_and_fix
        
        with pytest.raises(ValueError) as exc_info:
            scan_and_fix('style', 1, '*.py')  # String instead of list
        
        assert "must be a" in str(exc_info.value).lower()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

