#!/usr/bin/env python3
"""
Model Provider abstraction with automatic fallback support
"""
import os
import sys
import time
import random
from typing import Dict, List, Optional, Any
from abc import ABC, abstractmethod
import yaml
from common.utils import sanitize_error_message


class ModelProvider(ABC):
    """Base class for AI model providers"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.model = config['model']
        self.max_tokens = config.get('max_tokens', 4096)
        self.temperature = config.get('temperature', 0.3)
    
    @abstractmethod
    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Generate a response from the model"""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider is available"""
        pass


class AnthropicProvider(ModelProvider):
    """Anthropic Claude provider"""
    
    def is_available(self) -> bool:
        api_key_env = self.config.get('api_key_env', 'ANTHROPIC_API_KEY')
        return os.getenv(api_key_env) is not None
    
    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        try:
            import anthropic
            
            api_key_env = self.config.get('api_key_env', 'ANTHROPIC_API_KEY')
            client = anthropic.Anthropic(api_key=os.getenv(api_key_env))
            
            kwargs = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "messages": [{"role": "user", "content": prompt}]
            }
            
            if system_prompt:
                kwargs["system"] = system_prompt
            
            response = client.messages.create(**kwargs)
            return response.content[0].text
        except anthropic.APIError as e:
            safe_msg = sanitize_error_message(str(e))
            raise Exception(f"Anthropic API error: {safe_msg}")
        except anthropic.APIConnectionError as e:
            safe_msg = sanitize_error_message(str(e))
            raise Exception(f"Anthropic connection error: {safe_msg}")
        except Exception as e:
            safe_msg = sanitize_error_message(str(e))
            raise Exception(f"Anthropic unexpected error: {safe_msg}")


class OpenAIProvider(ModelProvider):
    """OpenAI GPT provider"""
    
    def is_available(self) -> bool:
        api_key_env = self.config.get('api_key_env', 'OPENAI_API_KEY')
        return os.getenv(api_key_env) is not None
    
    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        try:
            import openai
            
            api_key_env = self.config.get('api_key_env', 'OPENAI_API_KEY')
            client = openai.OpenAI(api_key=os.getenv(api_key_env))
            
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
            
            return response.choices[0].message.content
        except openai.APIError as e:
            safe_msg = sanitize_error_message(str(e))
            raise Exception(f"OpenAI API error: {safe_msg}")
        except openai.APIConnectionError as e:
            safe_msg = sanitize_error_message(str(e))
            raise Exception(f"OpenAI connection error: {safe_msg}")
        except Exception as e:
            safe_msg = sanitize_error_message(str(e))
            raise Exception(f"OpenAI unexpected error: {safe_msg}")


class GLMProvider(ModelProvider):
    """GLM (Zhipu AI) provider"""
    
    def is_available(self) -> bool:
        api_key_env = self.config.get('api_key_env', 'GLM_API_KEY')
        return os.getenv(api_key_env) is not None
    
    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        try:
            import requests
            
            api_key_env = self.config.get('api_key_env', 'GLM_API_KEY')
            api_base = self.config.get('api_base', 'https://api.z.ai/api/coding/paas/v4')
            
            headers = {
                'Authorization': f"Bearer {os.getenv(api_key_env)}",
                'Content-Type': 'application/json',
            }
            
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            url = f"{api_base}/chat/completions"
            
            data = {
                "model": self.model,
                "messages": messages,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
            }
            
            # GLM models can be slow, use longer timeout
            response = requests.post(url, headers=headers, json=data, timeout=120)
            response.raise_for_status()
            
            return response.json()['choices'][0]['message']['content']
        except requests.exceptions.HTTPError as e:
            # 429 (rate limit) should skip retries and fall back immediately
            if e.response.status_code == 429:
                safe_msg = sanitize_error_message(str(e))
                raise Exception(f"GLM rate limited (429): {safe_msg}")
            safe_msg = sanitize_error_message(str(e))
            raise Exception(f"GLM HTTP error: {safe_msg}")
        except requests.exceptions.ConnectionError as e:
            safe_msg = sanitize_error_message(str(e))
            raise Exception(f"GLM connection error: {safe_msg}")
        except requests.exceptions.Timeout as e:
            safe_msg = sanitize_error_message(str(e))
            raise Exception(f"GLM timeout error: {safe_msg}")
        except requests.exceptions.RequestException as e:
            safe_msg = sanitize_error_message(str(e))
            raise Exception(f"GLM request error: {safe_msg}")
        except Exception as e:
            safe_msg = sanitize_error_message(str(e))
            raise Exception(f"GLM unexpected error: {safe_msg}")


class CircuitBreaker:
    """Simple circuit breaker to prevent cascading failures
    
    Tracks consecutive failures per model and temporarily skips failing models
    within a single run when processing multiple files.
    """
    
    def __init__(self, failure_threshold: int = 3, reset_timeout: int = 60):
        """
        Args:
            failure_threshold: Number of consecutive failures before opening circuit (default: 3)
            reset_timeout: Seconds to wait before attempting to close circuit (default: 60)
        """
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.failures: Dict[str, int] = {}  # Model name -> consecutive failure count
        self.opened_at: Dict[str, float] = {}  # Model name -> timestamp when circuit opened
    
    def record_success(self, model_name: str) -> None:
        """Record successful call - resets failure count"""
        if model_name in self.failures:
            self.failures[model_name] = 0
        if model_name in self.opened_at:
            del self.opened_at[model_name]
    
    def record_failure(self, model_name: str) -> None:
        """Record failed call - increments failure count"""
        self.failures[model_name] = self.failures.get(model_name, 0) + 1
        
        # Open circuit if threshold exceeded
        if self.failures[model_name] >= self.failure_threshold:
            if model_name not in self.opened_at:
                self.opened_at[model_name] = time.time()
    
    def is_open(self, model_name: str) -> bool:
        """Check if circuit is open (model should be skipped)"""
        if model_name not in self.opened_at:
            return False
        
        # Check if reset timeout has elapsed
        elapsed = time.time() - self.opened_at[model_name]
        if elapsed >= self.reset_timeout:
            # Attempt to close circuit (half-open state)
            del self.opened_at[model_name]
            self.failures[model_name] = 0
            return False
        
        return True
    
    def get_status(self, model_name: str) -> str:
        """Get human-readable status of circuit"""
        if self.is_open(model_name):
            elapsed = time.time() - self.opened_at[model_name]
            remaining = self.reset_timeout - elapsed
            return f"OPEN (retry in {remaining:.0f}s)"
        elif model_name in self.failures and self.failures[model_name] > 0:
            return f"CLOSED ({self.failures[model_name]} failures)"
        else:
            return "CLOSED"


class ModelManager:
    """Manages models and provides fallback capabilities with circuit breaker pattern"""
    
    PROVIDERS = {
        'anthropic': AnthropicProvider,
        'openai': OpenAIProvider,
        'glm': GLMProvider,
    }
    
    def __init__(self, models_config_path: str):
        with open(models_config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.models = self.config['models']
        self.fallback_config = self.config.get('fallback', {})
        self.fallback_enabled = self.fallback_config.get('enabled', True)
        self.max_retries = self.fallback_config.get('max_retries', 3)
        self.retry_delay = self.fallback_config.get('retry_delay_seconds', 2)
        
        # Initialize circuit breaker for resilience within a run
        # When processing multiple files, if a model fails consistently,
        # stop trying it to avoid wasting time and API quota
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=3,  # Open circuit after 3 consecutive failures
            reset_timeout=60  # Try again after 1 minute (useful if run spans multiple files)
        )
        
        # Validate that at least one provider has API keys configured
        self._validate_api_keys()
    
    def _validate_api_keys(self) -> None:
        """Validate that at least one API key is configured
        
        Raises:
            RuntimeError: If no API keys are found for any configured provider
        """
        available_providers = []
        missing_keys = []
        
        # Check each configured model's provider
        for model_name, model_config in self.models.items():
            provider_type = model_config['provider']
            api_key_env = model_config.get('api_key_env', f"{provider_type.upper()}_API_KEY")
            
            if os.getenv(api_key_env):
                if provider_type not in available_providers:
                    available_providers.append(provider_type)
            else:
                if api_key_env not in missing_keys:
                    missing_keys.append(api_key_env)
        
        if not available_providers:
            error_msg = (
                "No API keys found for any configured model provider. "
                f"Please set at least one of the following environment variables: {', '.join(missing_keys)}. "
                "Available providers: anthropic (ANTHROPIC_API_KEY), openai (OPENAI_API_KEY), glm (GLM_API_KEY)"
            )
            raise RuntimeError(error_msg)
    
    def get_provider(self, model_name: str) -> ModelProvider:
        """Get a provider instance for a specific model"""
        if model_name not in self.models:
            raise ValueError(f"Model '{model_name}' not found in configuration")
        
        model_config = self.models[model_name]
        provider_type = model_config['provider']
        
        if provider_type not in self.PROVIDERS:
            raise ValueError(f"Unknown provider: {provider_type}")
        
        provider_class = self.PROVIDERS[provider_type]
        return provider_class(model_config)
    
    def generate_with_fallback(
        self,
        model_names: List[str],
        prompt: str,
        system_prompt: Optional[str] = None
    ) -> tuple[str, str]:
        """
        Generate response with automatic fallback
        Uses model order from agent config (not priority from models.yaml)
        Returns: (response, model_used)
        """
        if not model_names:
            raise ValueError("No models provided")
        
        last_error = None
        
        # Use the order specified by the agent (don't re-sort)
        for model_name in model_names:
            # Check circuit breaker first
            if self.circuit_breaker.is_open(model_name):
                circuit_status = self.circuit_breaker.get_status(model_name)
                print(f"  ⏭️  {model_name}: Circuit breaker {circuit_status}")
                sys.stdout.flush()
                continue
            
            provider = self.get_provider(model_name)
            
            # Check if provider is available
            if not provider.is_available():
                print(f"  ⏭️  {model_name}: Not available (missing credentials)")
                sys.stdout.flush()
                continue
            
            # Try with retries
            print(f"  🔄 Trying {model_name}...")
            sys.stdout.flush()
            for attempt in range(self.max_retries):
                try:
                    response = provider.generate(prompt, system_prompt)
                    # Success - record it in circuit breaker
                    self.circuit_breaker.record_success(model_name)
                    print(f"  ✓ {model_name}: Success")
                    sys.stdout.flush()
                    return response, model_name
                except Exception as e:
                    # Record failure in circuit breaker
                    self.circuit_breaker.record_failure(model_name)
                    last_error = e
                    error_msg = str(e)
                    # Check if it's a permanent error (auth, invalid key, rate limit) - don't retry
                    is_permanent_error = any(keyword in error_msg.lower() for keyword in [
                        '401', '403', '429', 'unauthorized', 'authentication', 'invalid api key',
                        'api key', 'forbidden', 'not found', '404', 'rate limit', 'too many requests',
                        'credit balance is too low'
                    ])
                    
                    if is_permanent_error:
                        print(f"  ✗ {model_name}: {error_msg[:150]} (skipping retries)")
                        sys.stdout.flush()
                        break  # Skip retries for permanent errors
                    
                    if attempt < self.max_retries - 1:
                        # Exponential backoff with jitter to avoid thundering herd
                        # Especially important for GLM which has concurrency limits
                        delay = self.retry_delay * (2 ** attempt) + random.uniform(0, 1)
                        print(f"  ⚠️  {model_name}: Attempt {attempt + 1} failed: {error_msg[:100]} (retry in {delay:.1f}s)")
                        sys.stdout.flush()
                        time.sleep(delay)
                    else:
                        print(f"  ✗ {model_name}: Failed after {self.max_retries} attempts: {error_msg[:150]}")
                        sys.stdout.flush()
            
            # If we get here, all retries failed for this model
            if not self.fallback_enabled:
                break
        
        # All models failed - provide actionable error message
        error_msg = f"All {len(model_names)} configured models failed."
        if last_error:
            # Only show the last error message, not every failure
            error_msg += f" Last error: {str(last_error)[:200]}"
        
        # Add suggestions for missing API keys
        missing_keys = []
        for model_name in model_names:
            try:
                provider = self.get_provider(model_name)
                if not provider.is_available():
                    model_config = self.models[model_name]
                    api_key_env = model_config.get('api_key_env', f"{model_config['provider'].upper()}_API_KEY")
                    if api_key_env not in missing_keys:
                        missing_keys.append(api_key_env)
            except Exception:
                pass  # Skip providers that couldn't be created
        
        if missing_keys:
            error_msg += f"\n\nMissing API keys: {', '.join(missing_keys)}"
            error_msg += "\nPlease configure at least one API key to enable AI code review."
        
        raise Exception(error_msg)


if __name__ == "__main__":
    # Test the model manager
    import os
    from pathlib import Path
    
    # Find config file relative to this script
    script_dir = Path(__file__).parent.parent
    config_path = script_dir.parent / 'config' / 'models.yaml'
    
    if not config_path.exists():
        print(f"Error: Config file not found at {config_path}")
        sys.exit(1)
    
    manager = ModelManager(str(config_path))
    
    try:
        response, model = manager.generate_with_fallback(
            ['claude_sonnet', 'openai_gpt4'],
            "Say hello!",
            "You are a helpful assistant."
        )
        print(f"\nModel used: {model}")
        print(f"Response: {response}")
    except Exception as e:
        print(f"Error: {e}")

