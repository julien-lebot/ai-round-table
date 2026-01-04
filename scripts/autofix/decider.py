"""
Auto-Fix Decider: Determines if an issue should be auto-fixed
"""
import yaml
from pathlib import Path
from typing import Tuple, Dict, Optional


class AutoFixDecider:
    """Decides if an issue should be auto-fixed"""
    
    def __init__(self, config_path: Optional[str] = None):
        """Initialize decider with configuration
        
        Args:
            config_path: Path to agents.yaml. If None, uses default location.
        """
        if config_path is None:
            # Default to agents.yaml in config directory
            script_dir = Path(__file__).parent.parent
            config_path = script_dir.parent / 'config' / 'agents.yaml'
        
        # Load safe-to-fix rules from configuration
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        autofix_config = config.get('settings', {}).get('autofix', {})
        self.safe_to_fix = autofix_config.get('safe_to_fix', {
            # Fallback defaults if config is missing
            'style': ['naming', 'formatting', 'imports', 'comments', 'dead code', 'unused'],
            'testing': ['missing tests', 'test coverage', 'assertion'],
            'performance': ['obvious optimization', 'caching', 'loop'],
            'security': ['input validation', 'sanitization']
        })
    
    def should_auto_fix(self, issue: Dict, agent_name: str) -> Tuple[bool, str]:
        """Decide if issue should be auto-fixed
        
        Args:
            issue: Issue dict with severity, category, description
            agent_name: Name of the agent that found the issue
            
        Returns:
            tuple: (should_fix, reason)
        """
        
        # Never auto-fix CRITICAL issues - too risky
        if issue['severity'] == 'CRITICAL':
            return False, "Critical issues require human review"
        
        # Only fix HIGH, MEDIUM or LOW
        if issue['severity'] not in ['HIGH', 'MEDIUM', 'LOW']:
            return False, f"Severity {issue['severity']} not in auto-fix range"
        
        # Check if category is safe
        category_lower = issue.get('category', '').lower()
        description_lower = issue.get('description', '').lower()
        
        for area, safe_categories in self.safe_to_fix.items():
            if area in agent_name.lower():
                for safe_cat in safe_categories:
                    if safe_cat in category_lower or safe_cat in description_lower:
                        return True, f"Safe category: {area}/{safe_cat}"
        
        return False, f"Category '{category_lower}' not in safe list"

