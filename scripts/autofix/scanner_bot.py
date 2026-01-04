#!/usr/bin/env python3
"""
Code Quality Scanner Bot
Scans repository for code quality issues and creates GitHub issues
"""
import os
import sys
import json
from pathlib import Path

# Add parent directories to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from autofix.engine import run_autofix_scan
from autofix.issue_creator import IssueCreator


def main() -> None:
    """Main entry point for code quality scanner"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Scan repository for code quality issues')
    parser.add_argument('--focus-area', default='style', 
                       choices=['security', 'performance', 'style', 'testing', 'architecture'],
                       help='Focus area for scanning')
    parser.add_argument('--file-patterns', default='*.py,*.js,*.ts,*.cs',
                       help='Comma-separated file patterns')
    parser.add_argument('--max-issues', type=int, default=20,
                       help='Maximum number of issues to create')
    parser.add_argument('--dry-run', action='store_true',
                       help='Print issues without creating them')
    
    args = parser.parse_args()
    
    print("🔍 Code Quality Scanner Starting")
    print(f"   Focus Area: {args.focus_area}")
    print(f"   File Patterns: {args.file_patterns}")
    print(f"   Max Issues: {args.max_issues}")
    if args.dry_run:
        print("   Mode: DRY RUN (no issues will be created)")
    
    # Get repository root
    repo_root = os.getenv('GITHUB_WORKSPACE', os.getcwd())
    
    # Run the scan (finds issues, doesn't generate fixes)
    file_patterns = [p.strip() for p in args.file_patterns.split(',')]
    scan_results = run_autofix_scan(
        repo_root=repo_root,
        focus_area=args.focus_area,
        file_patterns=file_patterns
    )
    
    # Collect all issues
    all_issues = []
    for result in scan_results:
        for issue in result['issues']:
            all_issues.append({
                'issue': issue,
                'agent': result['agent'],
                'file': result['file']
            })
    
    print(f"\n📊 Scan Results: Found {len(all_issues)} issue(s)")
    
    if not all_issues:
        print("   ✅ No issues found!")
        return
    
    # Limit to max issues
    all_issues = all_issues[:args.max_issues]
    
    if args.dry_run:
        print("\n📋 Issues (dry run):")
        for idx, item in enumerate(all_issues, 1):
            issue = item['issue']
            print(f"\n{idx}. {issue.category}: {issue.description[:60]}...")
            print(f"   File: {issue.file_path}")
            print(f"   Severity: {issue.severity}")
        return
    
    # Create GitHub issues
    github_token = os.getenv('GITHUB_TOKEN')
    github_repo = os.getenv('GITHUB_REPOSITORY')
    
    if not github_token or not github_repo:
        print("❌ GITHUB_TOKEN and GITHUB_REPOSITORY must be set")
        sys.exit(1)
    
    issue_creator = IssueCreator(github_token, github_repo)
    
    print("\n📝 Creating GitHub issues...")
    created_count = 0
    skipped_count = 0
    
    for idx, item in enumerate(all_issues, 1):
        issue = item['issue']
        agent = item['agent']
        
        print(f"\n[{idx}/{len(all_issues)}] {issue.category}: {issue.description[:50]}...")
        
        result = issue_creator.create_issue(issue, agent)
        
        if result:
            print(f"   ✅ Created issue #{result['number']}")
            created_count += 1
        else:
            print(f"   ⏭️  Skipped (duplicate)")
            skipped_count += 1
    
    print(f"\n✨ Summary:")
    print(f"   Created: {created_count}")
    print(f"   Skipped: {skipped_count}")
    print(f"   Total scanned: {len(all_issues)}")


if __name__ == '__main__':
    main()

