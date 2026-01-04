#!/usr/bin/env python3
"""
Tests for ModelManager and providers
"""
import pytest
import os
from unittest.mock import Mock, patch, MagicMock
import sys

# Add scripts directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from common.model_manager import ModelManager, AnthropicProvider, OpenAIProvider, GLMProvider
from common.utils import sanitize_error_message


class TestErrorSanitization:
    """Test error message sanitization"""
    
    def test_sanitize_api_key(self):
        error = "API key: sk-ant-abc123xyz789"
        sanitized = sanitize_error_message(error)
        assert "sk-ant" not in sanitized
        assert "[REDACTED]" in sanitized
    
    def test_sanitize_github_token(self):
        error = "Bearer ghp_1234567890abcdefghijklmnopqrstuvwxyz"
        sanitized = sanitize_error_message(error)
        assert "ghp_" not in sanitized
        assert "[REDACTED]" in sanitized
    
    def test_sanitize_authorization_header(self):
        error = "Authorization: Bearer secret-token-123"
        sanitized = sanitize_error_message(error)
        assert "secret-token" not in sanitized
        assert "[REDACTED]" in sanitized
    
    def test_sanitize_safe_message(self):
        error = "Connection timeout after 60 seconds"
        sanitized = sanitize_error_message(error)
        assert sanitized == error  # Should not change safe messages


class TestModelManager:
    """Test ModelManager functionality"""
    
    @pytest.fixture
    def models_config(self, tmp_path):
        """Create a temporary models config file"""
        config_file = tmp_path / "models.yaml"
        config_file.write_text("""
models:
  test_model:
    provider: anthropic
    model: claude-3-5-sonnet-20241022
    max_tokens: 100
    temperature: 0.3
    api_key_env: TEST_API_KEY

fallback:
  enabled: true
  max_retries: 2
  retry_delay_seconds: 0.1
""")
        return str(config_file)
    
    def test_model_manager_init(self, models_config):
        """Test ModelManager initialization"""
        manager = ModelManager(models_config)
        assert 'test_model' in manager.models
        assert manager.fallback_enabled is True
    
    def test_get_provider(self, models_config):
        """Test getting a provider instance"""
        manager = ModelManager(models_config)
        provider = manager.get_provider('test_model')
        assert isinstance(provider, AnthropicProvider)
        assert provider.model == 'claude-3-5-sonnet-20241022'
    
    def test_provider_not_available(self, models_config):
        """Test provider availability check"""
        manager = ModelManager(models_config)
        provider = manager.get_provider('test_model')
        
        # No API key set
        assert provider.is_available() is False
    
    @patch.dict(os.environ, {'TEST_API_KEY': 'test-key'})
    def test_provider_available(self, models_config):
        """Test provider is available when API key is set"""
        manager = ModelManager(models_config)
        provider = manager.get_provider('test_model')
        assert provider.is_available() is True
    
    def test_generate_with_fallback_no_models(self, models_config):
        """Test fallback with no available models"""
        manager = ModelManager(models_config)
        with pytest.raises(Exception) as exc_info:
            manager.generate_with_fallback(['test_model'], "test prompt")
        assert "not available" in str(exc_info.value).lower()


class TestProviderErrorHandling:
    """Test error handling in providers"""
    
    def test_anthropic_error_sanitization(self):
        """Test Anthropic errors are sanitized"""
        config = {
            'model': 'claude-3-5-sonnet-20241022',
            'max_tokens': 100,
            'temperature': 0.3,
            'api_key_env': 'TEST_KEY'
        }
        
        provider = AnthropicProvider(config)
        
        with patch.dict(os.environ, {'TEST_KEY': 'sk-ant-test123'}):
            with patch('anthropic.Anthropic') as mock_anthropic:
                mock_client = MagicMock()
                mock_anthropic.return_value = mock_client
                mock_client.messages.create.side_effect = Exception("API key: sk-ant-test123 leaked!")
                
                with pytest.raises(Exception) as exc_info:
                    provider.generate("test")
                
                # Error should be sanitized
                assert "sk-ant-test123" not in str(exc_info.value)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

