#!/usr/bin/env python3
"""
Issue Fixer Bot
Finds code-quality issues and attempts to fix them with PRs
"""
import os
import sys
import json
import requests
from pathlib import Path
from typing import List, Dict, Optional

# Add parent directories to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from autofix.fixer import CodeFixGenerator
from common.model_manager import ModelManager
from common.types import ReviewIssue
from autofix.formatter import format_pr_body
import hashlib


class IssueFixer:
    """Attempts to fix code-quality issues and create PRs"""
    
    def __init__(self, github_token: str, repo: str):
        self.token = github_token
        self.repo = repo
        self.api_base = "https://api.github.com"
        self.headers = {
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        # Get models config path relative to script location
        # Script is at .github/ai-review/scripts/autofix/issue_fixer_bot.py
        # Config is at .github/ai-review/config/models.yaml
        models_config_path = Path(__file__).parent.parent.parent / "config" / "models.yaml"
        self.model_manager = ModelManager(str(models_config_path))
        self.fixer = CodeFixGenerator(self.model_manager)
    
    def get_fixable_issues(self, max_issues: int = 10) -> List[Dict]:
        """Get open code-quality issues (optionally with fix-this label)"""
        url = f"{self.api_base}/repos/{self.repo}/issues"
        params = {
            "state": "open",
            "labels": "code-quality",
            "per_page": max_issues,
            "sort": "created",
            "direction": "desc"
        }
        
        response = requests.get(url, headers=self.headers, params=params, timeout=30)
        
        if response.status_code != 200:
            print(f"❌ Failed to fetch issues: {response.status_code}")
            return []
        
        return response.json()
    
    def parse_issue_to_review_issue(self, issue: Dict) -> Optional[ReviewIssue]:
        """Parse GitHub issue into ReviewIssue"""
        body = issue.get("body", "")
        
        # Extract metadata from issue body
        file_path = None
        line_number = None
        severity = "MEDIUM"
        category = "style"
        
        for line in body.split('\n'):
            if line.startswith('- **File:**'):
                file_path = line.split('`')[1] if '`' in line else None
            elif line.startswith('- **Line:**'):
                try:
                    line_number = int(line.split(':')[1].strip())
                except (ValueError, IndexError):
                    pass
            elif line.startswith('**Severity:**'):
                severity = line.split()[-1]
            elif line.startswith('**Category:**'):
                category = line.split(':')[1].strip()
        
        if not file_path:
            return None
        
        # Get description from title
        description = issue.get("title", "")
        
        return ReviewIssue(
            severity=severity,
            category=category,
            description=description,
            line_number=line_number,
            file_path=file_path,
            recommendation=""
        )
    
    def attempt_fix(self, issue_data: Dict) -> Optional[Dict]:
        """Attempt to generate a fix for an issue
        
        Returns:
            Fix dict with {title, body, files} or None if can't fix
        """
        issue_number = issue_data.get("number")
        print(f"\n🔧 Attempting to fix issue #{issue_number}: {issue_data.get('title', '')[:50]}...")
        
        review_issue = self.parse_issue_to_review_issue(issue_data)
        
        if not review_issue:
            print(f"   ❌ Could not parse issue")
            return None
        
        # Read file content
        file_path = Path(review_issue.file_path)
        if not file_path.exists():
            print(f"   ❌ File not found: {file_path}")
            return None
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            print(f"   ❌ Could not read file: {e}")
            return None
        
        # Generate fix
        print(f"   🤖 Generating fix...")
        fixed_content = self.fixer.generate_fix(review_issue, content)
        
        if not fixed_content or fixed_content == content:
            print(f"   ❌ No fix generated or no changes")
            return None
        
        print(f"   ✅ Fix generated!")
        
        # Create fix dict
        fix_id = hashlib.md5(f"{issue_number}:{file_path}".encode()).hexdigest()[:8]
        
        return {
            'id': fix_id,
            'title': f"Fix: {review_issue.description[:60]}",
            'body': format_pr_body(review_issue, "autofix"),
            'severity': review_issue.severity,
            'agent': "Issue Fixer Bot",
            'issue_number': issue_number,
            'files': [{
                'path': str(file_path),
                'content': fixed_content
            }]
        }


def main() -> None:
    """Main entry point for issue fixer bot"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Fix code-quality issues')
    parser.add_argument('--max-issues', type=int, default=5,
                       help='Maximum number of issues to attempt to fix')
    parser.add_argument('--dry-run', action='store_true',
                       help='Print fixes without creating PRs')
    parser.add_argument('--output', default='issue-fixes.json',
                       help='Output file for fixes')
    
    args = parser.parse_args()
    
    print("🔧 Issue Fixer Bot Starting")
    print(f"   Max Issues: {args.max_issues}")
    if args.dry_run:
        print("   Mode: DRY RUN")
    
    github_token = os.getenv('GITHUB_TOKEN')
    github_repo = os.getenv('GITHUB_REPOSITORY')
    
    if not github_token or not github_repo:
        print("❌ GITHUB_TOKEN and GITHUB_REPOSITORY must be set")
        sys.exit(1)
    
    fixer = IssueFixer(github_token, github_repo)
    
    # Get fixable issues
    print(f"\n📋 Fetching code-quality issues...")
    issues = fixer.get_fixable_issues(args.max_issues)
    
    if not issues:
        print("   ✅ No open code-quality issues found!")
        return
    
    print(f"   Found {len(issues)} issue(s) to attempt")
    
    # Attempt to fix each issue
    fixes = []
    for issue in issues:
        fix = fixer.attempt_fix(issue)
        if fix:
            fixes.append(fix)
    
    print(f"\n✨ Summary: Generated {len(fixes)} fix(es) from {len(issues)} issue(s)")
    
    if fixes:
        # Write fixes to output file
        with open(args.output, 'w') as f:
            json.dump(fixes, f, indent=2)
        print(f"   Fixes written to: {args.output}")
    else:
        print("   No fixes could be generated")


if __name__ == '__main__':
    main()

