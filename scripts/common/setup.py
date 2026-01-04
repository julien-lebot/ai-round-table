#!/usr/bin/env python3
"""
Setup and validation script for AI Code Review system
"""
import os
import sys
import yaml
from pathlib import Path


def check_file_exists(path: str) -> bool:
    """Check if a file exists"""
    return Path(path).exists()


def validate_yaml(path: str) -> tuple[bool, str]:
    """Validate YAML file"""
    try:
        with open(path, 'r') as f:
            yaml.safe_load(f)
        return True, "Valid"
    except Exception as e:
        return False, str(e)


def check_api_keys():
    """Check which API keys are configured"""
    keys = {
        'GITHUB_TOKEN': os.getenv('GITHUB_TOKEN'),
        'ANTHROPIC_API_KEY': os.getenv('ANTHROPIC_API_KEY'),
        'OPENAI_API_KEY': os.getenv('OPENAI_API_KEY'),
        'GLM_API_KEY': os.getenv('GLM_API_KEY'),
    }
    
    print("\n🔑 API Key Status:")
    available = []
    for key, value in keys.items():
        if value:
            print(f"  ✅ {key}: Configured")
            available.append(key)
        else:
            print(f"  ⚠️  {key}: Not configured")
    
    if not available:
        print("\n❌ No API keys configured!")
        print("   At least one API key is required.")
        print("   Add keys to GitHub Secrets or .env file")
        return False
    
    return True


def validate_config():
    """Validate configuration files"""
    print("\n📋 Validating Configuration Files:")
    
    base_path = Path(".github/ai-review")
    
    files = {
        "Models Config": base_path / "config/models.yaml",
        "Agents Config": base_path / "config/agents.yaml",
        "Requirements": base_path / "requirements.txt",
        "Model Manager": base_path / "scripts/common/model_manager.py",
        "Review Agents": base_path / "scripts/review/agents.py",
        "Review Script": base_path / "scripts/review/review_pr.py",
        "Autofix Engine": base_path / "scripts/autofix/engine.py",
    }
    
    all_valid = True
    
    for name, path in files.items():
        if not path.exists():
            print(f"  ❌ {name}: Not found at {path}")
            all_valid = False
        elif path.suffix == '.yaml':
            valid, msg = validate_yaml(path)
            if valid:
                print(f"  ✅ {name}: Valid")
            else:
                print(f"  ❌ {name}: Invalid - {msg}")
                all_valid = False
        else:
            print(f"  ✅ {name}: Found")
    
    return all_valid


def validate_models_config():
    """Validate models configuration"""
    print("\n🤖 Validating Models Configuration:")
    
    config_path = Path(".github/ai-review/config/models.yaml")
    
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    if 'models' not in config:
        print("  ❌ No 'models' section found")
        return False
    
    print(f"  📦 Found {len(config['models'])} models:")
    
    for model_name, model_config in config['models'].items():
        provider = model_config.get('provider', 'unknown')
        priority = model_config.get('priority', 'N/A')
        print(f"    - {model_name} ({provider}, priority: {priority})")
    
    if 'fallback' in config:
        fallback = config['fallback']
        enabled = fallback.get('enabled', False)
        strategy = fallback.get('strategy', [])
        print(f"\n  🔄 Fallback: {'Enabled' if enabled else 'Disabled'}")
        if enabled and strategy:
            print(f"     Strategy: {' → '.join(strategy)}")
    
    return True


def validate_agents_config():
    """Validate agents configuration"""
    print("\n👥 Validating Agents Configuration:")
    
    config_path = Path(".github/ai-review/config/agents.yaml")
    
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    if 'agents' not in config:
        print("  ❌ No 'agents' section found")
        return False
    
    agents = config['agents']
    
    # Check for master agent
    master_agents = [a for a, c in agents.items() if c.get('role') == 'master']
    if not master_agents:
        print("  ❌ No master agent found")
        return False
    
    print(f"  ✅ Master Agent: {agents[master_agents[0]]['name']}")
    
    specialist_agents = [a for a, c in agents.items() if c.get('role') == 'specialist']
    print(f"  ✅ Found {len(specialist_agents)} specialist agents:")
    
    for agent_id in specialist_agents:
        agent = agents[agent_id]
        name = agent.get('name', agent_id)
        weight = agent.get('weight', 'N/A')
        models = agent.get('models', [])
        print(f"    - {name} (weight: {weight}, models: {len(models)})")
    
    return True


def check_workflows():
    """Check GitHub Actions workflows"""
    print("\n⚙️  Checking GitHub Actions Workflows:")
    
    workflows_path = Path(".github/workflows")
    
    required_workflows = [
        "ai-review.yml",
        "auto-merge.yml"
    ]
    
    all_found = True
    
    for workflow in required_workflows:
        path = workflows_path / workflow
        if path.exists():
            print(f"  ✅ {workflow}")
        else:
            print(f"  ❌ {workflow}: Not found")
            all_found = False
    
    return all_found


def test_imports():
    """Test if required Python packages can be imported"""
    print("\n📦 Testing Python Dependencies:")
    
    required = [
        ('yaml', 'pyyaml'),
        ('requests', 'requests'),
    ]
    
    optional = [
        ('anthropic', 'anthropic'),
        ('openai', 'openai'),
    ]
    
    all_required = True
    
    for module, package in required:
        try:
            __import__(module)
            print(f"  ✅ {package}")
        except ImportError:
            print(f"  ❌ {package}: Not installed")
            all_required = False
    
    print("\n  Optional dependencies:")
    for module, package in optional:
        try:
            __import__(module)
            print(f"  ✅ {package}")
        except ImportError:
            print(f"  ⚠️  {package}: Not installed (optional)")
    
    if not all_required:
        print("\n  Install required packages:")
        print("  pip install -r .github/ai-review/requirements.txt")
    
    return all_required


def print_summary(results: dict):
    """Print validation summary"""
    print("\n" + "="*60)
    print("📊 Validation Summary")
    print("="*60)
    
    all_passed = all(results.values())
    
    for check, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}: {check}")
    
    print("="*60)
    
    if all_passed:
        print("\n🎉 All checks passed! System is ready to use.")
        print("\nNext steps:")
        print("  1. Add API keys to GitHub Secrets")
        print("  2. Commit and push the configuration")
        print("  3. Open a test PR to trigger the review")
        return 0
    else:
        print("\n⚠️  Some checks failed. Please fix the issues above.")
        return 1


def main():
    print("🚀 AI Code Review System - Setup Validation")
    print("="*60)
    
    results = {
        "Configuration Files": validate_config(),
        "Models Configuration": validate_models_config(),
        "Agents Configuration": validate_agents_config(),
        "GitHub Workflows": check_workflows(),
        "Python Dependencies": test_imports(),
        "API Keys": check_api_keys(),
    }
    
    return print_summary(results)


if __name__ == "__main__":
    sys.exit(main())

