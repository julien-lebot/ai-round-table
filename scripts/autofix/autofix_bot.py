#!/usr/bin/env python3
"""
Auto-Fix Bot: Finds issues and generates fixes
Proactively scans codebase and creates PRs with fixes

This is a thin wrapper that delegates to the refactored module structure.
Maintains backward compatibility for existing workflows.
"""
from autofix.cli import main

if __name__ == "__main__":
    main()
