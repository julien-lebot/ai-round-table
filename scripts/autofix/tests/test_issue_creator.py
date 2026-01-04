"""
Tests for IssueCreator
"""
import unittest
from unittest.mock import Mock, patch, MagicMock
from autofix.issue_creator import IssueCreator
from common.types import ReviewIssue


class TestIssueCreator(unittest.TestCase):
    """Test IssueCreator logic"""
    
    def setUp(self):
        self.creator = IssueCreator("fake-token", "owner/repo")
    
    def test_compute_issue_hash_consistent(self):
        """Test that same issue generates same hash"""
        issue1 = ReviewIssue(
            severity="MEDIUM",
            category="style",
            description="Test issue description",
            file_path="test.py",
            line_number=10
        )
        issue2 = ReviewIssue(
            severity="MEDIUM",
            category="style",
            description="Test issue description",
            file_path="test.py",
            line_number=10
        )
        hash1 = self.creator._compute_issue_hash(issue1)
        hash2 = self.creator._compute_issue_hash(issue2)
        self.assertEqual(hash1, hash2)
    
    def test_compute_issue_hash_different_file(self):
        """Test that different files generate different hashes"""
        issue1 = ReviewIssue(
            severity="MEDIUM",
            category="style",
            description="Test issue",
            file_path="test1.py"
        )
        issue2 = ReviewIssue(
            severity="MEDIUM",
            category="style",
            description="Test issue",
            file_path="test2.py"
        )
        hash1 = self.creator._compute_issue_hash(issue1)
        hash2 = self.creator._compute_issue_hash(issue2)
        self.assertNotEqual(hash1, hash2)
    
    def test_compute_issue_hash_truncates_description(self):
        """Test that long descriptions are truncated for hash"""
        long_desc = "A" * 200
        issue = ReviewIssue(
            severity="MEDIUM",
            category="style",
            description=long_desc,
            file_path="test.py"
        )
        hash_val = self.creator._compute_issue_hash(issue)
        # Should not fail and should be 12 chars
        self.assertEqual(len(hash_val), 12)
    
    @patch('autofix.issue_creator.requests.get')
    def test_get_existing_issue_hashes_empty(self, mock_get):
        """Test getting hashes when no issues exist"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_get.return_value = mock_response
        
        hashes = self.creator._get_existing_issue_hashes()
        self.assertEqual(len(hashes), 0)
    
    @patch('autofix.issue_creator.requests.get')
    def test_get_existing_issue_hashes_extracts_hash(self, mock_get):
        """Test extracting hash from issue body"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{
            "body": "Some issue text\n<!-- issue-hash: abc123def456 -->"
        }]
        mock_get.return_value = mock_response
        
        hashes = self.creator._get_existing_issue_hashes()
        self.assertIn("abc123def456", hashes)
    
    @patch('autofix.issue_creator.requests.post')
    @patch('autofix.issue_creator.requests.get')
    def test_create_issue_skips_duplicate(self, mock_get, mock_post):
        """Test that duplicate issues are skipped"""
        # Mock existing issues with matching hash
        issue = ReviewIssue(
            severity="MEDIUM",
            category="style",
            description="Test issue",
            file_path="test.py"
        )
        issue_hash = self.creator._compute_issue_hash(issue)
        
        mock_get_response = Mock()
        mock_get_response.status_code = 200
        mock_get_response.json.return_value = [{
            "body": f"<!-- issue-hash: {issue_hash} -->"
        }]
        mock_get.return_value = mock_get_response
        
        result = self.creator.create_issue(issue, "Test Agent")
        
        # Should not create issue
        self.assertIsNone(result)
        mock_post.assert_not_called()
    
    @patch('autofix.issue_creator.requests.post')
    @patch('autofix.issue_creator.requests.get')
    def test_create_issue_success(self, mock_get, mock_post):
        """Test successful issue creation"""
        # No existing issues
        mock_get_response = Mock()
        mock_get_response.status_code = 200
        mock_get_response.json.return_value = []
        mock_get.return_value = mock_get_response
        
        # Successful creation
        mock_post_response = Mock()
        mock_post_response.status_code = 201
        mock_post_response.json.return_value = {"number": 123}
        mock_post.return_value = mock_post_response
        
        issue = ReviewIssue(
            severity="MEDIUM",
            category="style",
            description="Test issue",
            file_path="test.py"
        )
        
        result = self.creator.create_issue(issue, "Test Agent")
        
        self.assertIsNotNone(result)
        self.assertEqual(result["number"], 123)
        mock_post.assert_called_once()


if __name__ == '__main__':
    unittest.main()

