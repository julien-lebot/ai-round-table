#!/usr/bin/env python3
"""
Tests for review_pr.py functionality
"""
import pytest
import json
import sys
import os
from unittest.mock import Mock, patch, MagicMock

# Add scripts directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


class TestPRInfoFetching:
    """Test PR info fetching"""
    
    @patch('review.review_pr.os.getenv')
    def test_get_pr_info_success(self, mock_getenv):
        """Test successful PR info retrieval"""
        mock_getenv.return_value = '/tmp/event.json'
        
        event_data = {
            'pull_request': {
                'number': 1,
                'title': 'Test PR',
                'body': 'Test description',
                'user': {'login': 'testuser'},
                'base': {'ref': 'main'},
                'head': {'ref': 'feature', 'sha': 'abc123def456'},
                'diff_url': 'https://api.github.com/repos/owner/repo/pulls/1'
            }
        }
        
        with patch('builtins.open', create=True) as mock_open:
            mock_open.return_value.__enter__.return_value.read.return_value = json.dumps(event_data)
            from review.review_pr import get_pr_info
            
            result = get_pr_info()
            assert result['number'] == 1
            assert result['title'] == 'Test PR'
    
    @patch('review.review_pr.os.getenv')
    def test_get_pr_info_missing_env(self, mock_getenv):
        """Test error when GITHUB_EVENT_PATH is missing"""
        mock_getenv.return_value = None
        
        from review.review_pr import get_pr_info
        with pytest.raises(ValueError):
            get_pr_info()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

