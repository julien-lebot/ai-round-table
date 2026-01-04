"""
CLI Interface: Command-line entry point for Auto-Fix Bot
"""
import sys
import json
import argparse
from pathlib import Path

# Add scripts directory to path for imports
scripts_dir = Path(__file__).parent.parent
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from autofix.engine import scan_and_fix


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description='Auto-Fix Bot: Proactively find and fix code issues'
    )
    parser.add_argument(
        '--focus-area',
        default='style',
        choices=['security', 'performance', 'style', 'testing', 'architecture'],
        help='Focus area for fixes (default: style)'
    )
    parser.add_argument(
        '--max-prs',
        type=int,
        default=3,
        help='Maximum number of PRs to create (default: 3)'
    )
    parser.add_argument(
        '--file-patterns',
        default='*.py,*.js,*.ts',
        help='Comma-separated file patterns to scan (default: *.py,*.js,*.ts)'
    )
    parser.add_argument(
        '--output',
        default='fixes.json',
        help='Output file for fix data (default: fixes.json)'
    )
    
    args = parser.parse_args()
    
    # Parse file patterns
    file_patterns = [p.strip() for p in args.file_patterns.split(',')]
    
    # Run scan and fix
    try:
        fixes = scan_and_fix(args.focus_area, args.max_prs, file_patterns)
        
        # Save results
        with open(args.output, 'w') as f:
            json.dump(fixes, f, indent=2)
        
        print(f"\n✨ Generated {len(fixes)} fix(es)")
        print(f"   Output: {args.output}")
        
        if fixes:
            print("\n📋 Fixes:")
            for fix in fixes:
                print(f"   - {fix['title']}")
        
        sys.exit(0)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

