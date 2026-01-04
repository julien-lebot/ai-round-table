"""
Tests for AutoFixDecider
"""
import unittest
from autofix.decider import AutoFixDecider


class TestAutoFixDecider(unittest.TestCase):
    """Test AutoFixDecider logic"""
    
    def setUp(self):
        self.decider = AutoFixDecider()
    
    def test_critical_never_auto_fixed(self):
        """Test that CRITICAL issues are never auto-fixed"""
        issue = {
            'severity': 'CRITICAL',
            'category': 'security',
            'description': 'SQL injection vulnerability'
        }
        should_fix, reason = self.decider.should_auto_fix(issue, 'Security Review Agent')
        self.assertFalse(should_fix)
        self.assertIn('Critical', reason)
    
    def test_safe_style_issue(self):
        """Test that safe style issues can be auto-fixed"""
        issue = {
            'severity': 'LOW',
            'category': 'naming',
            'description': 'Variable name should follow convention'
        }
        should_fix, reason = self.decider.should_auto_fix(issue, 'Style Review Agent')
        self.assertTrue(should_fix)
        self.assertIn('Safe category', reason)
    
    def test_unsafe_category(self):
        """Test that unsafe categories are not auto-fixed"""
        issue = {
            'severity': 'MEDIUM',
            'category': 'architecture',
            'description': 'Consider refactoring to use design pattern'
        }
        should_fix, reason = self.decider.should_auto_fix(issue, 'Architecture Review Agent')
        self.assertFalse(should_fix)
        self.assertIn('not in safe list', reason)
    
    def test_invalid_severity(self):
        """Test that invalid severities are not auto-fixed"""
        issue = {
            'severity': 'UNKNOWN',
            'category': 'style',
            'description': 'Some issue'
        }
        should_fix, reason = self.decider.should_auto_fix(issue, 'Style Review Agent')
        self.assertFalse(should_fix)
        self.assertIn('not in auto-fix range', reason)


if __name__ == '__main__':
    unittest.main()

