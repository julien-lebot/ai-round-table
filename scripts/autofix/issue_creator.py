"""
Issue Creator: Creates GitHub issues for code quality problems
"""
import hashlib
import requests
from typing import List, Dict, Set, Optional
from common.types import ReviewIssue


class IssueCreator:
    """Creates GitHub issues and checks for duplicates"""
    
    def __init__(self, github_token: str, repo: str):
        """
        Args:
            github_token: GitHub API token
            repo: Repository in format "owner/repo"
        """
        self.token = github_token
        self.repo = repo
        self.api_base = "https://api.github.com"
        self.headers = {
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
    
    def _compute_issue_hash(self, issue: ReviewIssue) -> str:
        """Compute unique hash for issue to detect duplicates"""
        # Create signature from file, category, and normalized description
        signature = f"{issue.file_path}:{issue.category}:{issue.description[:100]}"
        return hashlib.md5(signature.encode()).hexdigest()[:12]
    
    def _get_existing_issue_hashes(self) -> Set[str]:
        """Get hashes of all existing open code-quality issues"""
        url = f"{self.api_base}/repos/{self.repo}/issues"
        params = {
            "state": "open",
            "labels": "code-quality",
            "per_page": 100
        }
        
        hashes = set()
        page = 1
        
        while True:
            params["page"] = page
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            
            if response.status_code != 200:
                print(f"  ⚠️  Failed to fetch existing issues: {response.status_code}")
                break
            
            issues = response.json()
            if not issues:
                break
            
            # Extract hash from issue body (hidden comment)
            for issue in issues:
                body = issue.get("body", "")
                if "<!-- issue-hash:" in body:
                    hash_start = body.find("<!-- issue-hash:") + 16
                    hash_end = body.find("-->", hash_start)
                    if hash_end > hash_start:
                        issue_hash = body[hash_start:hash_end].strip()
                        hashes.add(issue_hash)
            
            page += 1
            if len(issues) < 100:  # Last page
                break
        
        return hashes
    
    def create_issue(self, issue: ReviewIssue, agent_name: str) -> Optional[Dict]:
        """Create GitHub issue if it doesn't already exist
        
        Args:
            issue: The code issue to report
            agent_name: Name of agent that found it
            
        Returns:
            Created issue dict or None if duplicate
        """
        issue_hash = self._compute_issue_hash(issue)
        
        # Check if issue already exists
        existing_hashes = self._get_existing_issue_hashes()
        if issue_hash in existing_hashes:
            return None  # Duplicate, skip
        
        # Create issue title
        title = f"{issue.category.title()}: {issue.description[:80]}"
        if len(issue.description) > 80:
            title += "..."
        
        # Create issue body
        severity_emoji = {
            "CRITICAL": "🔴",
            "HIGH": "🟠",
            "MEDIUM": "🟡",
            "LOW": "🟢"
        }
        
        body = f"""## Code Quality Issue

**Severity:** {severity_emoji.get(issue.severity, '⚪')} {issue.severity}
**Category:** {issue.category}
**Found by:** {agent_name}

### Location
- **File:** `{issue.file_path}`
"""
        
        if issue.line_number:
            body += f"- **Line:** {issue.line_number}\n"
        
        body += f"""
### Description

{issue.description}

### Suggested Fix

{issue.suggestion or "Review and fix according to best practices."}

---

*This issue was automatically detected by the Code Quality Scanner.*
*Add the `fix-this` label for the bot to attempt an automated fix.*

<!-- issue-hash: {issue_hash} -->
"""
        
        # Determine labels
        labels = ["code-quality", issue.severity.lower(), issue.category.lower()]
        
        # Create the issue
        url = f"{self.api_base}/repos/{self.repo}/issues"
        data = {
            "title": title,
            "body": body,
            "labels": labels
        }
        
        response = requests.post(url, headers=self.headers, json=data, timeout=30)
        
        if response.status_code == 201:
            return response.json()
        else:
            print(f"  ❌ Failed to create issue: {response.status_code} - {response.text[:200]}")
            return None

