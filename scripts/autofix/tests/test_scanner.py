"""
Tests for file scanner
"""
import unittest
import tempfile
import shutil
from pathlib import Path
from autofix.scanner import should_scan_file, discover_files, generate_synthetic_diff


class TestScanner(unittest.TestCase):
    """Test file scanning functions"""
    
    def setUp(self):
        """Create temporary directory for tests"""
        self.test_dir = tempfile.mkdtemp()
        self.test_path = Path(self.test_dir)
    
    def tearDown(self):
        """Clean up temporary directory"""
        shutil.rmtree(self.test_dir)
    
    def test_should_scan_file_normal(self):
        """Test that normal files should be scanned"""
        file_path = self.test_path / "src" / "main.py"  # Use non-test path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.touch()
        self.assertTrue(should_scan_file(file_path))
    
    def test_should_scan_file_skip_node_modules(self):
        """Test that node_modules files are skipped"""
        file_path = self.test_path / "node_modules" / "test.js"
        file_path.parent.mkdir()
        file_path.touch()
        self.assertFalse(should_scan_file(file_path))
    
    def test_should_scan_file_skip_test_files(self):
        """Test that test files are skipped"""
        file_path = self.test_path / "test_file.py"
        file_path.touch()
        self.assertFalse(should_scan_file(file_path))
    
    def test_generate_synthetic_diff(self):
        """Test synthetic diff generation"""
        content = "line1\nline2\nline3"
        diff = generate_synthetic_diff("test.py", content)
        self.assertIn("diff --git", diff)
        self.assertIn("+++ b/test.py", diff)
        self.assertIn("+line1", diff)
        self.assertIn("+line2", diff)
        self.assertIn("+line3", diff)
    
    def test_generate_synthetic_diff_truncates(self):
        """Test that large files are truncated in diff"""
        # Create content with more than 500 lines
        content = "\n".join([f"line{i}" for i in range(600)])
        diff = generate_synthetic_diff("test.py", content)
        self.assertIn("truncated", diff)


if __name__ == '__main__':
    unittest.main()

