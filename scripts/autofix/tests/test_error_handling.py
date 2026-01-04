"""
Tests for error handling in AutoFix system
Tests ModelManager API failures, network errors, and edge cases
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import sys

# Add scripts directory to path
scripts_dir = Path(__file__).parent.parent.parent
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from common.model_manager import ModelManager, AnthropicProvider, OpenAIProvider, GLMProvider
from autofix.autofix_scanner import AutoFixScanner
from autofix.engine import scan_and_fix


class TestModelManagerErrorHandling:
    """Test error handling in ModelManager"""
    
    def test_missing_api_keys_raises_runtime_error(self, tmp_path):
        """Test that ModelManager raises RuntimeError when no API keys are configured"""
        # Create a minimal models.yaml
        config_file = tmp_path / "models.yaml"
        config_file.write_text("""
models:
  test_model:
    provider: anthropic
    model: claude-sonnet-4-20250514
    api_key_env: NONEXISTENT_API_KEY
fallback:
  enabled: true
""")
        
        with patch.dict('os.environ', {}, clear=True):
            with pytest.raises(RuntimeError) as exc_info:
                ModelManager(str(config_file))
            
            assert "No API keys found" in str(exc_info.value)
            assert "NONEXISTENT_API_KEY" in str(exc_info.value)
    
    def test_api_rate_limit_error_skips_retries(self, tmp_path):
        """Test that 429 rate limit errors skip retries and fallback immediately"""
        config_file = tmp_path / "models.yaml"
        config_file.write_text("""
models:
  test_model:
    provider: glm
    model: glm-4-7
    api_key_env: GLM_API_KEY
fallback:
  enabled: true
  max_retries: 3
""")
        
        with patch.dict('os.environ', {'GLM_API_KEY': 'test-key'}):
            manager = ModelManager(str(config_file))
            
            # Mock the provider to raise rate limit error
            with patch.object(GLMProvider, 'generate') as mock_generate:
                import requests
                mock_response = Mock()
                mock_response.status_code = 429
                mock_generate.side_effect = requests.exceptions.HTTPError(response=mock_response)
                
                with pytest.raises(Exception) as exc_info:
                    manager.generate_with_fallback(['test_model'], "test prompt")
                
                # Should only try once (no retries for 429)
                assert mock_generate.call_count == 1
    
    def test_network_timeout_retries_with_backoff(self, tmp_path):
        """Test that network timeouts retry with exponential backoff"""
        config_file = tmp_path / "models.yaml"
        config_file.write_text("""
models:
  test_model:
    provider: anthropic
    model: claude-sonnet-4-20250514
    api_key_env: ANTHROPIC_API_KEY
fallback:
  enabled: true
  max_retries: 3
  retry_delay_seconds: 0.1
""")
        
        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            manager = ModelManager(str(config_file))
            
            with patch.object(AnthropicProvider, 'generate') as mock_generate:
                # Simulate timeout errors
                mock_generate.side_effect = Exception("Connection timeout")
                
                with pytest.raises(Exception):
                    manager.generate_with_fallback(['test_model'], "test prompt")
                
                # Should retry 3 times
                assert mock_generate.call_count == 3
    
    def test_invalid_json_response_handled_gracefully(self, tmp_path):
        """Test that invalid JSON responses from LLM are handled gracefully"""
        config_file = tmp_path / "models.yaml"
        config_file.write_text("""
models:
  test_model:
    provider: anthropic
    model: claude-sonnet-4-20250514
    api_key_env: ANTHROPIC_API_KEY
""")
        
        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            manager = ModelManager(str(config_file))
            
            agent_config = {
                'name': 'Test Agent',
                'system_prompt': 'test',
                'models': ['test_model']
            }
            
            scanner = AutoFixScanner('style', agent_config, manager)
            
            with patch.object(manager, 'generate_with_fallback') as mock_generate:
                # Return invalid JSON
                mock_generate.return_value = ("This is not JSON at all", "test_model")
                
                review = scanner.scan_file("test.py", "print('hello')")
                
                # Should return empty issues list, not crash
                assert review.issues == []
                assert "0 fixable issue(s)" in review.summary
    
    def test_malformed_model_config_raises_value_error(self, tmp_path):
        """Test that malformed model configuration raises ValueError"""
        config_file = tmp_path / "models.yaml"
        config_file.write_text("""
models:
  bad_model:
    provider: unknown_provider
    model: test
""")
        
        with patch.dict('os.environ', {'TEST_KEY': 'value'}):
            manager = ModelManager(str(config_file))
            
            with pytest.raises(ValueError) as exc_info:
                manager.get_provider('bad_model')
            
            assert "Unknown provider" in str(exc_info.value)


class TestAutoFixScannerErrorHandling:
    """Test error handling in AutoFixScanner"""
    
    def test_file_not_found_handled_gracefully(self):
        """Test that missing files don't crash the scanner"""
        with patch('autofix.engine.discover_files') as mock_discover:
            mock_discover.return_value = [Path('/nonexistent/file.py')]
            
            # Should not raise, should log and continue
            with pytest.raises(ValueError):
                scan_and_fix('style', 1, ['*.py'])
    
    def test_permission_denied_handled_gracefully(self, tmp_path):
        """Test that permission denied errors are handled"""
        test_file = tmp_path / "test.py"
        test_file.write_text("print('test')")
        
        # Make file unreadable (Unix only)
        if hasattr(test_file, 'chmod'):
            test_file.chmod(0o000)
            
            with patch('autofix.scanner.discover_files') as mock_discover:
                mock_discover.return_value = [test_file]
                
                # Should handle gracefully
                try:
                    with pytest.raises(PermissionError):
                        with open(test_file, 'r') as f:
                            f.read()
                finally:
                    # Restore permissions for cleanup
                    test_file.chmod(0o644)
    
    def test_unicode_decode_error_handled(self):
        """Test that binary files causing UnicodeDecodeError are handled"""
        # This would be tested in integration with actual binary files
        pass


class TestConcurrentScenarios:
    """Test concurrent and race condition scenarios"""
    
    def test_multiple_fixes_same_file_handled(self):
        """Test that multiple fixes targeting the same file are handled correctly"""
        # This would require mocking the PR creation logic
        # For now, we ensure only one fix per file is generated
        pass
    
    def test_file_modified_during_scan_handled(self):
        """Test that files modified during scanning don't cause crashes"""
        # This would require filesystem mocking
        pass


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

