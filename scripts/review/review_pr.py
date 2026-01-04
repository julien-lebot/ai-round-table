#!/usr/bin/env python3
"""
Main review script - Called by GitHub Actions
"""
import os
import sys
import json
import argparse
import time
from typing import Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add scripts directory to path for imports
from pathlib import Path
scripts_dir = Path(__file__).parent.parent
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from review.agents import AgentOrchestrator
from common.types import ReviewDecision, IssueSeverity


def get_pr_info() -> Dict[str, Any]:
    """Get PR information from GitHub context"""
    github_event_path = os.getenv('GITHUB_EVENT_PATH')
    
    if not github_event_path:
        raise ValueError("GITHUB_EVENT_PATH environment variable not found")
    
    try:
        with open(github_event_path, 'r') as f:
            event = json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"GitHub event file not found: {github_event_path}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in GitHub event file: {str(e)}")
    
    if 'pull_request' not in event:
        raise ValueError("GitHub event does not contain pull_request data")
    
    pr = event['pull_request']
    
    return {
        'number': pr['number'],
        'title': pr['title'],
        'description': pr.get('body', ''),
        'author': pr['user']['login'],
        'base': pr['base']['ref'],
        'head': pr['head']['ref'],
        'head_sha': pr['head']['sha'],  # Needed for inline comments
        'diff_url': pr['diff_url'],
    }


def get_pr_diff(pr_number: int) -> str:
    """Fetch PR diff using GitHub API"""
    import requests
    
    repo = os.getenv('GITHUB_REPOSITORY')
    token = os.getenv('GITHUB_TOKEN')
    
    if not repo:
        raise ValueError("GITHUB_REPOSITORY environment variable not found")
    if not token:
        raise ValueError("GITHUB_TOKEN environment variable not found")
    
    # Use the API endpoint, not the web URL
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    
    headers = {
        'Authorization': f"token {token}",
        'Accept': 'application/vnd.github.v3.diff'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.text
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            raise FileNotFoundError(f"PR #{pr_number} not found")
        raise Exception(f"GitHub API HTTP error: {str(e)}")
    except requests.exceptions.ConnectionError as e:
        raise Exception(f"GitHub API connection error: {str(e)}")
    except requests.exceptions.Timeout as e:
        raise Exception(f"GitHub API timeout: {str(e)}")
    except requests.exceptions.RequestException as e:
        raise Exception(f"GitHub API request error: {str(e)}")


def get_changed_files(pr_number: int) -> list[str]:
    """Get list of changed files from GitHub API"""
    import requests
    
    repo = os.getenv('GITHUB_REPOSITORY')
    token = os.getenv('GITHUB_TOKEN')
    
    if not repo:
        raise ValueError("GITHUB_REPOSITORY environment variable not found")
    if not token:
        raise ValueError("GITHUB_TOKEN environment variable not found")
    
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files"
    
    headers = {
        'Authorization': f"token {token}",
        'Accept': 'application/vnd.github.v3+json'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        files = response.json()
        return [f['filename'] for f in files]
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            raise FileNotFoundError(f"PR #{pr_number} not found")
        raise Exception(f"GitHub API HTTP error: {str(e)}")
    except requests.exceptions.RequestException as e:
        raise Exception(f"GitHub API request error: {str(e)}")
    except (KeyError, TypeError) as e:
        raise ValueError(f"Unexpected response format from GitHub API: {str(e)}")


def should_skip_file(file_path: str, skip_patterns: list[str]) -> bool:
    """Check if file should be skipped"""
    import fnmatch
    
    for pattern in skip_patterns:
        if fnmatch.fnmatch(file_path, pattern):
            return True
    return False


def format_decision_text(decision: ReviewDecision) -> str:
    """Format decision enum to human-readable text"""
    mapping = {
        ReviewDecision.APPROVE: "Approve",
        ReviewDecision.REQUEST_CHANGES: "Request Changes",
        ReviewDecision.DEFER_TO_HUMAN: "Defer to Human"
    }
    return mapping.get(decision, decision.value.replace('_', ' ').title())


def format_review_comment(review) -> str:
    """Format review as GitHub comment"""
    
    decision_emoji = {
        ReviewDecision.APPROVE: "✅",
        ReviewDecision.REQUEST_CHANGES: "⚠️",
        ReviewDecision.DEFER_TO_HUMAN: "👤"
    }
    
    emoji = decision_emoji.get(review.decision, "❓")
    decision_text = format_decision_text(review.decision)
    
    # Count inline issues for reference (only CRITICAL/HIGH with line numbers)
    inline_issues = sum(
        len([i for i in r.issues 
             if i.file_path and i.line_number 
             and i.severity in [IssueSeverity.CRITICAL, IssueSeverity.HIGH]])
        for r in review.agent_reviews
    )
    
    # Summary section - add extra text for APPROVE to make it clear
    header = f"## {emoji} {decision_text}"
    if review.decision == ReviewDecision.APPROVE:
        header += "\n\n**🤖 AI Review: APPROVED** - No significant issues found. This code meets quality standards."
    
    comment = f"""{header}

{review.reasoning}

"""

    if inline_issues > 0:
        comment += f"💡 *{inline_issues} inline comment(s) posted on specific code lines (CRITICAL/HIGH severity only)*\n\n"
    
    comment += "---\n\n"
    
    # Recommendations (if any)
    if review.recommendations:
        comment += "### 💡 Top Recommendations\n\n"
        for i, rec in enumerate(review.recommendations[:5], 1):  # Limit to top 5
            comment += f"{i}. {rec}\n"
        comment += "\n---\n\n"
    
    # Agent reviews - show all issues that are NOT posted as inline comments
    # This includes: issues without file/line, and MEDIUM/LOW/INFO issues (even with line numbers)
    agents_with_summary_issues = [
        r for r in review.agent_reviews 
        if any(not (i.file_path and i.line_number and i.severity in [IssueSeverity.CRITICAL, IssueSeverity.HIGH]) 
               for i in r.issues)
    ]
    if agents_with_summary_issues:
        comment += "### 🔍 Issues Summary\n\n"
        comment += "*Note: CRITICAL/HIGH severity issues with specific line numbers are posted as inline comments above. All other issues are listed here.*\n\n"
        
        for agent_review in agents_with_summary_issues:
            # Agent header
            status_icon = "✅" if len(agent_review.issues) == 0 else "⚠️"
            comment += f"#### {status_icon} {agent_review.agent_name}\n\n"
            
            if agent_review.summary and agent_review.summary != "Agent unavailable":
                comment += f"*{agent_review.summary}*\n\n"
            
            # Filter to issues that are NOT posted as inline comments
            # (no file/line, or MEDIUM/LOW/INFO severity)
            summary_issues = [
                i for i in agent_review.issues 
                if not (i.file_path and i.line_number and i.severity in [IssueSeverity.CRITICAL, IssueSeverity.HIGH])
            ]
            
            if not summary_issues:
                continue
            
            # Group by severity
            by_severity = {}
            for issue in summary_issues:
                sev = issue.severity.value
                if sev not in by_severity:
                    by_severity[sev] = []
                by_severity[sev].append(issue)
            
            # Show by severity order
            severity_order = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO']
            for severity in severity_order:
                if severity not in by_severity:
                    continue
                
                issues = by_severity[severity]
                severity_icon = {
                    'CRITICAL': '🔴',
                    'HIGH': '🟠',
                    'MEDIUM': '🟡',
                    'LOW': '🔵',
                    'INFO': 'ℹ️'
                }.get(severity, '•')
                
                comment += f"**{severity_icon} {severity} ({len(issues)})**\n\n"
                
                for issue in issues:
                    # Issue description
                    comment += f"- {issue.description}"
                    if issue.file_path:
                        if issue.line_number:
                            comment += f" → `{issue.file_path}:{issue.line_number}`"
                        else:
                            comment += f" → `{issue.file_path}`"
                    comment += "\n"
                    
                    # Suggestion if available
                    if issue.suggestion:
                        comment += f"  💡 *{issue.suggestion}*\n"
                
                comment += "\n"
            
            comment += "---\n\n"
    
    # Footer
    comment += f"<sub>Reviewed by {review.model_used} • {review.timestamp}</sub>"
    
    return comment


def get_existing_pr_comments(pr_number: int) -> list:
    """Fetch existing inline comments on the PR to avoid duplicates"""
    import requests
    
    repo = os.getenv('GITHUB_REPOSITORY')
    token = os.getenv('GITHUB_TOKEN')
    
    if not repo or not token:
        return []
    
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/comments"
    
    headers = {
        'Authorization': f"token {token}",
        'Accept': 'application/vnd.github.v3+json'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception:
        # If we can't fetch comments, proceed without deduplication
        return []


def is_similar_comment(new_body: str, existing_body: str, similarity_threshold: float = 0.7) -> bool:
    """Check if two comment bodies are similar enough to be considered duplicates
    
    Uses both word-based Jaccard similarity and sequence matching for better accuracy.
    """
    import difflib
    
    if not new_body or not existing_body:
        return False
    
    # Normalize: remove markdown formatting, extra whitespace, and convert to lowercase
    def normalize(text: str) -> str:
        # Remove markdown bold/italic markers
        text = text.replace('**', '').replace('*', '').replace('`', '')
        # Remove emojis and special characters (keep alphanumeric and basic punctuation)
        import re
        text = re.sub(r'[^\w\s]', ' ', text)
        # Normalize whitespace
        text = ' '.join(text.lower().split())
        return text
    
    normalized_new = normalize(new_body)
    normalized_existing = normalize(existing_body)
    
    if not normalized_new or not normalized_existing:
        return False
    
    # Method 1: Word-based Jaccard similarity
    new_words = set(normalized_new.split())
    existing_words = set(normalized_existing.split())
    
    if new_words and existing_words:
        intersection = new_words & existing_words
        union = new_words | existing_words
        jaccard_similarity = len(intersection) / len(union) if union else 0
    else:
        jaccard_similarity = 0
    
    # Method 2: Sequence-based similarity (handles reordered words)
    sequence_similarity = difflib.SequenceMatcher(None, normalized_new, normalized_existing).ratio()
    
    # Use the higher of the two similarities
    similarity = max(jaccard_similarity, sequence_similarity)
    
    return similarity >= similarity_threshold


def validate_line_number(file_path: str, line_number: int, changed_files: list) -> bool:
    """Validate that a line number seems reasonable for a file in the PR
    
    Args:
        file_path: Path to the file
        line_number: Line number to validate
        changed_files: List of changed file information from GitHub API
    
    Returns:
        True if line number seems valid, False otherwise
    """
    if line_number <= 0:
        return False
    
    # Very conservative upper bound - most files are < 10000 lines
    if line_number > 50000:
        return False
    
    # TODO: Could fetch actual file and validate line exists
    # For now, basic sanity checks
    return True


def post_inline_comment(pr_number: int, head_sha: str, file_path: str, line_number: int, body: str, existing_comments: list = None, changed_files: list = None):
    """Post an inline comment on a specific line of code
    
    Args:
        pr_number: PR number
        head_sha: Commit SHA
        file_path: File path
        line_number: Line number in the file (NOT diff-relative)
        body: Comment body
        existing_comments: Optional list of existing comments for deduplication
        changed_files: Optional list of changed files for validation
    """
    import requests
    
    repo = os.getenv('GITHUB_REPOSITORY')
    token = os.getenv('GITHUB_TOKEN')
    
    if not repo:
        raise ValueError("GITHUB_REPOSITORY environment variable not found")
    if not token:
        raise ValueError("GITHUB_TOKEN environment variable not found")
    
    # Validate line number
    if not validate_line_number(file_path, line_number, changed_files or []):
        return None
    
    # Check for duplicate comments based on file + content similarity
    # This handles cases where code moved (line numbers changed) but the issue is the same
    if existing_comments:
        for comment in existing_comments:
            # Check if comment is on the same file (line number may have changed after fixes)
            if comment.get('path') == file_path:
                # Check content similarity (not line number, since code can move)
                if is_similar_comment(body, comment.get('body', '')):
                    # Skip duplicate comment (same file, similar content)
                    return {'status': 'duplicate', 'comment_id': comment.get('id')}
    
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/comments"
    
    headers = {
        'Authorization': f"token {token}",
        'Accept': 'application/vnd.github.v3+json'
    }
    
    # GitHub inline comments require commit SHA, path, line, and side
    data = {
        'body': body,
        'commit_id': head_sha,
        'path': file_path,
        'line': line_number,
        'side': 'RIGHT'  # Comment on the PR branch (not base)
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            # File or line might not exist in the diff - skip silently
            return None
        elif e.response.status_code == 422:
            # Invalid line number or file - skip silently
            # This often happens when line_number is diff-relative instead of file-relative
            return None
        # Log but don't fail the whole review for inline comment errors
        print(f"  ⚠️  Failed to post inline comment on {file_path}:{line_number}")
        return None
    except requests.exceptions.RequestException:
        # Don't fail review if inline comments fail
        print(f"  ⚠️  Error posting inline comment on {file_path}:{line_number}")
        return None


def post_review_comment(pr_number: int, comment: str):
    """Post review comment to GitHub PR"""
    import requests
    
    repo = os.getenv('GITHUB_REPOSITORY')
    token = os.getenv('GITHUB_TOKEN')
    
    if not repo:
        raise ValueError("GITHUB_REPOSITORY environment variable not found")
    if not token:
        raise ValueError("GITHUB_TOKEN environment variable not found")
    
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    
    headers = {
        'Authorization': f"token {token}",
        'Accept': 'application/vnd.github.v3+json'
    }
    
    data = {'body': comment}
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        print(f"✅ Posted review comment to PR #{pr_number}")
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            raise FileNotFoundError(f"PR #{pr_number} not found")
        raise Exception(f"GitHub API HTTP error: {str(e)}")
    except requests.exceptions.RequestException as e:
        raise Exception(f"GitHub API request error: {str(e)}")


def post_agent_inline_comments(pr_number: int, head_sha: str, agent_reviews, changed_files: list = None):
    """Post inline comments for issues with file_path and line_number
    
    Only posts inline comments for CRITICAL and HIGH severity issues.
    MEDIUM/LOW/INFO issues go in the summary comment.
    
    Args:
        pr_number: PR number
        head_sha: Commit SHA
        agent_reviews: List of agent reviews
        changed_files: Optional list of changed files for validation
    """
    from review.agents import AgentReview, IssueSeverity
    
    inline_count = 0
    failed_count = 0
    duplicate_count = 0
    invalid_count = 0
    filtered_count = 0
    
    # Fetch existing comments for deduplication
    print(f"  Fetching existing comments for deduplication...")
    existing_comments = get_existing_pr_comments(pr_number)
    print(f"  Found {len(existing_comments)} existing comment(s)")
    
    for agent_review in agent_reviews:
        if not agent_review.issues:
            continue
        
        # Group issues by file and line for better organization
        # ONLY include CRITICAL and HIGH severity issues for inline comments
        issues_by_location = {}
        for issue in agent_review.issues:
            # Filter: Only CRITICAL and HIGH severity issues get inline comments
            if issue.severity not in [IssueSeverity.CRITICAL, IssueSeverity.HIGH]:
                filtered_count += 1
                continue
                
            if issue.file_path and issue.line_number:
                # Validate line number is positive
                if issue.line_number <= 0:
                    invalid_count += 1
                    continue
                key = (issue.file_path, issue.line_number)
                if key not in issues_by_location:
                    issues_by_location[key] = []
                issues_by_location[key].append(issue)
        
        # Post inline comments
        for (file_path, line_number), issues in issues_by_location.items():
            # Format comment body
            severity_icons = {
                IssueSeverity.CRITICAL: '🔴',
                IssueSeverity.HIGH: '🟠',
                IssueSeverity.MEDIUM: '🟡',
                IssueSeverity.LOW: '🔵',
                IssueSeverity.INFO: 'ℹ️'
            }
            
            comment_body = f"**{agent_review.agent_name}**\n\n"
            
            for issue in issues:
                icon = severity_icons.get(issue.severity, '•')
                comment_body += f"{icon} **{issue.severity.value}**: {issue.description}\n"
                if issue.suggestion:
                    comment_body += f"\n💡 *{issue.suggestion}*\n"
                if issue.code_snippet:
                    comment_body += f"\n```\n{issue.code_snippet}\n```\n"
                comment_body += "\n"
            
            # Post the inline comment with deduplication and validation
            result = post_inline_comment(pr_number, head_sha, file_path, line_number, comment_body, existing_comments, changed_files)
            if result:
                if isinstance(result, dict) and result.get('status') == 'duplicate':
                    duplicate_count += 1
                else:
                    inline_count += 1
            else:
                failed_count += 1
    
    if filtered_count > 0:
        print(f"  ℹ️  Filtered {filtered_count} issue(s) to summary (MEDIUM/LOW/INFO severity)")
    if invalid_count > 0:
        print(f"  ⚠️  Skipped {invalid_count} comment(s) with invalid line numbers")
    if duplicate_count > 0:
        print(f"  ℹ️  Skipped {duplicate_count} duplicate comment(s) (same file + similar content)")
    if failed_count > 0:
        print(f"  ⚠️  {failed_count} inline comment(s) could not be posted (file/line may not exist in diff)")
    
    return inline_count


def submit_pr_review(pr_number: int, head_sha: str, review, comment: str, changed_files: list = None):
    """Submit an actual GitHub PR review with approval/changes requested status
    
    This repository has "Allow GitHub Actions to create and approve pull requests" enabled,
    so we can submit real APPROVE reviews.
    """
    import requests
    
    repo = os.getenv('GITHUB_REPOSITORY')
    token = os.getenv('GITHUB_TOKEN')
    
    if not repo:
        raise ValueError("GITHUB_REPOSITORY environment variable not found")
    if not token:
        raise ValueError("GITHUB_TOKEN environment variable not found")
    
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews"
    
    headers = {
        'Authorization': f"token {token}",
        'Accept': 'application/vnd.github.v3+json'
    }
    
    # Map AI decision to GitHub review event
    event_map = {
        ReviewDecision.APPROVE: 'APPROVE',
        ReviewDecision.REQUEST_CHANGES: 'REQUEST_CHANGES',
        ReviewDecision.DEFER_TO_HUMAN: 'COMMENT'
    }
    
    event = event_map.get(review.decision, 'COMMENT')
    
    # Ensure body is not empty - GitHub API requires a non-empty body for reviews
    if not comment or not comment.strip():
        comment = "No issues found. Code looks good! ✅"
    
    data = {
        'body': comment,
        'event': event
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        
        review_data = response.json()
        
        print(f"✅ Submitted GitHub PR review: {event}")
        print(f"   Review ID: {review_data.get('id')}")
        print(f"   State: {review_data.get('state')}")
        
        # Post inline comments for actionable issues
        print(f"\n📝 Posting inline comments for actionable issues...")
        inline_count = post_agent_inline_comments(pr_number, head_sha, review.agent_reviews, changed_files)
        if inline_count > 0:
            print(f"✅ Posted {inline_count} inline comment(s) on specific code lines")
        else:
            print(f"ℹ️  No inline comments (issues without file/line info are in summary)")
        
        return review_data
    except requests.exceptions.HTTPError as e:
        # Log the full error response for debugging
        error_details = ""
        try:
            error_body = e.response.json()
            error_details = f"\nResponse body: {error_body}"
        except:
            error_details = f"\nResponse text: {e.response.text}"
        
        print(f"❌ GitHub API error ({e.response.status_code}): {error_details}")
        print(f"   Request body was: {data}")
        
        if e.response.status_code == 404:
            raise FileNotFoundError(f"PR #{pr_number} not found")
        elif e.response.status_code == 422:
            raise ValueError(f"Invalid review data: {str(e)}{error_details}")
        raise Exception(f"GitHub API HTTP error: {str(e)}{error_details}")
    except requests.exceptions.RequestException as e:
        raise Exception(f"GitHub API request error: {str(e)}")


def save_review_output(review, output_file: str):
    """Save review output for GitHub Actions"""
    
    output = {
        'decision': review.decision.value,
        'reasoning': review.reasoning,
        'critical_count': review.critical_issues_count,
        'high_count': review.high_issues_count,
        'recommendations': review.recommendations,
        'should_approve': review.decision == ReviewDecision.APPROVE,
        'should_request_changes': review.decision == ReviewDecision.REQUEST_CHANGES,
        'should_defer': review.decision == ReviewDecision.DEFER_TO_HUMAN,
    }
    
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)
    
    # Also set GitHub Actions outputs
    github_output = os.getenv('GITHUB_OUTPUT')
    if github_output:
        with open(github_output, 'a') as f:
            f.write(f"decision={review.decision.value}\n")
            f.write(f"should_approve={str(review.decision == ReviewDecision.APPROVE).lower()}\n")
            f.write(f"critical_count={review.critical_issues_count}\n")


def main():
    parser = argparse.ArgumentParser(description='AI Code Review')
    parser.add_argument('--agents-config', default='.github/ai-review/config/agents.yaml')
    parser.add_argument('--models-config', default='.github/ai-review/config/models.yaml')
    parser.add_argument('--output', default='review-output.json')
    parser.add_argument('--dry-run', action='store_true', help='Run without posting to GitHub')
    
    args = parser.parse_args()
    
    try:
        start_time = time.time()
        print("🚀 Starting AI Code Review")
        sys.stdout.flush()
        
        # Get PR info (needed first for PR number)
        pr_info = get_pr_info()
        print(f"📝 Reviewing PR #{pr_info['number']}: {pr_info['title']}")
        sys.stdout.flush()
        
        # Fetch diff and files in parallel
        print("📥 Fetching PR diff and changed files in parallel...")
        sys.stdout.flush()
        
        with ThreadPoolExecutor(max_workers=2) as executor:
            diff_future = executor.submit(get_pr_diff, pr_info['number'])
            files_future = executor.submit(get_changed_files, pr_info['number'])
            
            diff = diff_future.result()
            files = files_future.result()
        
        print(f"✓ Diff fetched ({len(diff)} chars)")
        print(f"✓ Found {len(files)} changed files")
        
        # Initialize orchestrator
        print("🤖 Initializing AI agents...")
        orchestrator = AgentOrchestrator(args.agents_config, args.models_config)
        print(f"✓ Initialized {len(orchestrator.agents)} specialist agents + master")
        
        # Perform review
        print("\n🔍 Starting review process...")
        print("=" * 60)
        review = orchestrator.review_pr(
            diff=diff,
            file_list=files,
            pr_description=pr_info['description']
        )
        print("=" * 60)
        
        elapsed = time.time() - start_time
        print(f"\n✨ Review Complete!")
        print(f"Decision: {format_decision_text(review.decision)}")
        print(f"Critical Issues: {review.critical_issues_count}")
        print(f"High Issues: {review.high_issues_count}")
        print(f"Time: {elapsed:.1f}s")
        sys.stdout.flush()
        
        # Format comment
        comment = format_review_comment(review)
        
        # Submit actual GitHub PR review (not just a comment)
        if not args.dry_run:
            print("\n📤 Submitting GitHub PR review...")
            submit_pr_review(pr_info['number'], pr_info['head_sha'], review, comment, files)
        else:
            print("\n--- DRY RUN: Would submit PR review ---")
            print(f"Event: {review.decision.value}")
            print(comment)
        
        # Save output
        save_review_output(review, args.output)
        
        # Exit code based on decision
        if review.decision == ReviewDecision.REQUEST_CHANGES:
            print("\n⚠️  Review requests changes")
            sys.exit(1)
        elif review.decision == ReviewDecision.DEFER_TO_HUMAN:
            print("\n👤 Review deferred to human")
            sys.exit(2)
        else:
            print("\n✅ Review approved")
            sys.exit(0)
    
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(3)


if __name__ == "__main__":
    main()

