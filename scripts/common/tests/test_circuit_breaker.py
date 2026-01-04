"""
Tests for circuit breaker pattern in ModelManager
"""
import pytest
import time
from pathlib import Path
import sys
from unittest.mock import Mock, patch, MagicMock
import yaml
import tempfile
import os

# Add scripts directory to path
scripts_dir = Path(__file__).parent.parent.parent
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from common.model_manager import CircuitBreaker, ModelManager


class TestCircuitBreaker:
    """Test circuit breaker functionality"""
    
    def test_circuit_starts_closed(self):
        """Test that circuit breaker starts in closed state"""
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=10)
        
        assert not cb.is_open('test_model')
        assert cb.get_status('test_model') == 'CLOSED'
    
    def test_circuit_opens_after_threshold_failures(self):
        """Test that circuit opens after exceeding failure threshold"""
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=10)
        
        # Record failures below threshold
        cb.record_failure('test_model')
        cb.record_failure('test_model')
        assert not cb.is_open('test_model')
        
        # One more failure should open circuit
        cb.record_failure('test_model')
        assert cb.is_open('test_model')
        assert 'OPEN' in cb.get_status('test_model')
    
    def test_success_resets_failure_count(self):
        """Test that success resets failure count"""
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=10)
        
        # Record some failures
        cb.record_failure('test_model')
        cb.record_failure('test_model')
        
        # Record success - should reset
        cb.record_success('test_model')
        
        # Circuit should still be closed
        assert not cb.is_open('test_model')
        assert cb.get_status('test_model') == 'CLOSED'
    
    def test_circuit_closes_after_timeout(self):
        """Test that circuit closes after reset timeout"""
        cb = CircuitBreaker(failure_threshold=2, reset_timeout=1)  # 1 second timeout
        
        # Open the circuit
        cb.record_failure('test_model')
        cb.record_failure('test_model')
        assert cb.is_open('test_model')
        
        # Wait for timeout
        time.sleep(1.1)
        
        # Circuit should close (half-open state)
        assert not cb.is_open('test_model')
    
    def test_multiple_models_tracked_independently(self):
        """Test that multiple models are tracked independently"""
        cb = CircuitBreaker(failure_threshold=2, reset_timeout=10)
        
        # Fail model A
        cb.record_failure('model_a')
        cb.record_failure('model_a')
        
        # model_a should be open, model_b should be closed
        assert cb.is_open('model_a')
        assert not cb.is_open('model_b')


class TestModelManagerCircuitBreaker:
    """Test circuit breaker integration in ModelManager"""
    
    def setup_method(self):
        """Set up test fixtures"""
        # Create temporary config file
        self.test_dir = tempfile.mkdtemp()
        self.config_path = Path(self.test_dir) / 'models.yaml'
        
        config = {
            'models': {
                'test_model_1': {
                    'provider': 'openai',
                    'model': 'gpt-3.5-turbo',
                    'max_tokens': 1000,
                    'temperature': 0.3,
                    'api_key_env': 'TEST_API_KEY_1'
                },
                'test_model_2': {
                    'provider': 'anthropic',
                    'model': 'claude-3-sonnet',
                    'max_tokens': 1000,
                    'temperature': 0.3,
                    'api_key_env': 'TEST_API_KEY_2'
                }
            },
            'fallback': {
                'enabled': True,
                'max_retries': 2,
                'retry_delay_seconds': 0.1
            }
        }
        
        with open(self.config_path, 'w') as f:
            yaml.dump(config, f)
        
        # Set test API keys
        os.environ['TEST_API_KEY_1'] = 'test_key_1'
        os.environ['TEST_API_KEY_2'] = 'test_key_2'
    
    def teardown_method(self):
        """Clean up test fixtures"""
        if 'TEST_API_KEY_1' in os.environ:
            del os.environ['TEST_API_KEY_1']
        if 'TEST_API_KEY_2' in os.environ:
            del os.environ['TEST_API_KEY_2']
        
        import shutil
        if self.test_dir:
            shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def test_circuit_breaker_prevents_repeated_failures(self):
        """Test that circuit breaker prevents calling failing models repeatedly"""
        manager = ModelManager(str(self.config_path))
        
        # Manually open circuit for test_model_1 (3 failures to match threshold)
        for _ in range(3):
            manager.circuit_breaker.record_failure('test_model_1')
        
        assert manager.circuit_breaker.is_open('test_model_1')
        
        # Mock providers to track calls
        with patch.object(manager, 'get_provider') as mock_get_provider:
            mock_provider = Mock()
            mock_provider.is_available.return_value = True
            mock_provider.generate.side_effect = Exception("Provider failed")
            mock_get_provider.return_value = mock_provider
            
            # Try to generate with test_model_1 - should skip it
            with pytest.raises(Exception) as exc_info:
                manager.generate_with_fallback(['test_model_1'], 'test prompt')
            
            # Provider should not be called because circuit is open
            # (but get_provider is called to check availability)
            assert 'failed' in str(exc_info.value).lower()
    
    def test_successful_call_closes_circuit(self):
        """Test that successful calls close the circuit"""
        manager = ModelManager(str(self.config_path))
        
        # Open circuit (3 failures to match threshold)
        for _ in range(3):
            manager.circuit_breaker.record_failure('test_model_1')
        
        # Reset timeout to allow immediate retry
        manager.circuit_breaker.reset_timeout = 0
        
        # Mock successful provider call
        with patch.object(manager, 'get_provider') as mock_get_provider:
            mock_provider = Mock()
            mock_provider.is_available.return_value = True
            mock_provider.generate.return_value = "Success"
            mock_get_provider.return_value = mock_provider
            
            # Should succeed and close circuit
            response, model_used = manager.generate_with_fallback(['test_model_1'], 'test prompt')
            
            assert response == "Success"
            assert model_used == 'test_model_1'
            assert not manager.circuit_breaker.is_open('test_model_1')


class TestModelManagerErrorMessages:
    """Test improved error messages in ModelManager"""
    
    def setup_method(self):
        """Set up test fixtures"""
        # Create temporary config file
        self.test_dir = tempfile.mkdtemp()
        self.config_path = Path(self.test_dir) / 'models.yaml'
        
        config = {
            'models': {
                'test_model': {
                    'provider': 'openai',
                    'model': 'gpt-3.5-turbo',
                    'max_tokens': 1000,
                    'temperature': 0.3,
                    'api_key_env': 'MISSING_API_KEY'
                }
            },
            'fallback': {
                'enabled': True,
                'max_retries': 1,
                'retry_delay_seconds': 0.1
            }
        }
        
        with open(self.config_path, 'w') as f:
            yaml.dump(config, f)
    
    def teardown_method(self):
        """Clean up test fixtures"""
        import shutil
        if self.test_dir:
            shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def test_missing_api_key_error_message(self):
        """Test that missing API key error provides helpful message"""
        # Don't set the API key
        with pytest.raises(RuntimeError) as exc_info:
            ModelManager(str(self.config_path))
        
        error_msg = str(exc_info.value)
        assert 'No API keys found' in error_msg
        assert 'MISSING_API_KEY' in error_msg or 'ANTHROPIC_API_KEY' in error_msg or 'OPENAI_API_KEY' in error_msg
    
    def test_all_models_failed_error_includes_suggestions(self):
        """Test that failure error includes suggestions for missing API keys"""
        # Set one API key but make provider fail
        os.environ['MISSING_API_KEY'] = 'test_key'
        
        try:
            manager = ModelManager(str(self.config_path))
            
            # Mock provider to always fail
            with patch.object(manager, 'get_provider') as mock_get_provider:
                mock_provider = Mock()
                mock_provider.is_available.return_value = False
                mock_get_provider.return_value = mock_provider
                
                with pytest.raises(Exception) as exc_info:
                    manager.generate_with_fallback(['test_model'], 'test prompt')
                
                error_msg = str(exc_info.value)
                # Should provide helpful error message
                assert 'failed' in error_msg.lower()
        finally:
            if 'MISSING_API_KEY' in os.environ:
                del os.environ['MISSING_API_KEY']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

