"""
AutoFix Engine: Main scanning and fixing logic for autofix bot
"""
import sys
import hashlib
import logging
from pathlib import Path
from typing import List, Dict

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Maximum file size to scan (20KB - matches LLM scan limit)
MAX_FILE_SIZE_BYTES = 20 * 1024  # 20KB

# Add scripts directory to path for imports
scripts_dir = Path(__file__).parent.parent
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from autofix.autofix_scanner import AutoFixScanner
from common.model_manager import ModelManager
from autofix.decider import AutoFixDecider
from autofix.fixer import CodeFixGenerator
from autofix.scanner import get_repo_root, discover_files
from autofix.formatter import format_pr_body
import yaml


def run_autofix_scan(repo_root: str, focus_area: str, file_patterns: List[str]) -> List[Dict]:
    """Scan codebase and return found issues (no fixes generated)
    
    Used by scanner bot to find issues and create GitHub issues.
    
    Args:
        repo_root: Repository root path
        focus_area: Area to focus on
        file_patterns: File patterns to scan
        
    Returns:
        List of dicts with {file, agent, issues[]}
    """
    # Load configuration
    config_dir = Path(__file__).parent.parent.parent / 'config'
    agents_config_path = config_dir / 'agents.yaml'
    models_config_path = config_dir / 'models.yaml'
    
    with open(agents_config_path) as f:
        agents_config = yaml.safe_load(f)
    
    # Map focus area to agent
    agent_mapping = {
        'security': 'security',
        'performance': 'performance',
        'style': 'style',
        'testing': 'testing',
        'architecture': 'architecture'
    }
    
    agent_id = agent_mapping.get(focus_area.lower())
    if not agent_id:
        raise ValueError(f"Invalid focus_area: {focus_area}")
    
    # Initialize model manager
    model_manager = ModelManager(models_config_path)
    
    # Create scanner
    agent_config = agents_config['agents'][agent_id]
    settings = agents_config.get('settings', {})
    scanner = AutoFixScanner(
        focus_area=focus_area,
        agent_config=agent_config,
        model_manager=model_manager,
        settings=settings,
        repo_root=Path(repo_root)
    )
    
    # Discover files
    files_to_scan = discover_files(Path(repo_root), file_patterns)
    files_to_scan = files_to_scan[:50]  # Limit for performance
    
    # Scan each file
    results = []
    for file_path in files_to_scan:
        try:
            # Check file size before reading to avoid memory issues with large files
            file_size = file_path.stat().st_size
            if file_size > MAX_FILE_SIZE_BYTES:
                logger.debug(f"Skipping {file_path}: file too large ({file_size} bytes > {MAX_FILE_SIZE_BYTES})")
                continue
            
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            review = scanner.scan_file(str(file_path), content)
            
            if review.issues:
                results.append({
                    'file': str(file_path),
                    'agent': review.agent_name,
                    'issues': review.issues
                })
        except Exception as e:
            logger.warning(f"Error scanning {file_path}: {e}")
            continue
    
    return results


def scan_and_fix(focus_area: str, max_prs: int, file_patterns: List[str] = None) -> List[Dict]:
    """Main autofix function: scan codebase, find issues, generate fixes
    
    Args:
        focus_area: Area to focus on (security, performance, style, testing)
        max_prs: Maximum number of PRs to create
        file_patterns: File patterns to scan (default: ['*.py', '*.js', '*.ts'])
        
    Returns:
        List of fix dicts ready for PR creation
        
    Raises:
        ValueError: If input parameters are invalid
    """
    
    # Input validation
    if not focus_area or not isinstance(focus_area, str):
        raise ValueError("focus_area must be a non-empty string")
    
    valid_focus_areas = ['security', 'performance', 'style', 'testing', 'architecture']
    if focus_area.lower() not in valid_focus_areas:
        raise ValueError(f"focus_area must be one of: {', '.join(valid_focus_areas)}")
    
    if not isinstance(max_prs, int) or max_prs < 1 or max_prs > 50:
        raise ValueError("max_prs must be an integer between 1 and 50")
    
    if file_patterns is None:
        file_patterns = ['*.py', '*.js', '*.ts', '*.java', '*.cs']
    
    if not isinstance(file_patterns, list) or not file_patterns:
        raise ValueError("file_patterns must be a non-empty list")
    
    # Validate file patterns
    for pattern in file_patterns:
        if not isinstance(pattern, str) or not pattern.strip():
            raise ValueError(f"Invalid file pattern: {pattern}")
    
    fixes = []
    
    # Get repository root
    repo_root = get_repo_root()
    logger.info("🤖 Auto-Fix Bot Starting")
    logger.info(f"   Repository Root: {repo_root}")
    logger.info(f"   Focus Area: {focus_area}")
    logger.info(f"   Max PRs: {max_prs}")
    logger.info(f"   File Patterns: {', '.join(file_patterns)}")
    
    # Initialize
    logger.info("\n📋 Initializing autofix scanner...")
    # Use absolute paths from repo root
    agents_config_path = repo_root / '.github' / 'ai-review' / 'config' / 'agents.yaml'
    models_config_path = repo_root / '.github' / 'ai-review' / 'config' / 'models.yaml'
    
    # Load configs
    with open(agents_config_path, 'r') as f:
        agents_config = yaml.safe_load(f)
    
    # Initialize model manager (shared resource)
    model_manager = ModelManager(str(models_config_path))
    
    # Map focus_area to agent ID in config
    FOCUS_AREA_TO_AGENT_ID = {
        'style': 'style',
        'security': 'security',
        'performance': 'performance',
        'testing': 'testing',
        'architecture': 'architecture'
    }
    
    agent_id = FOCUS_AREA_TO_AGENT_ID.get(focus_area.lower())
    if not agent_id or agent_id not in agents_config['agents']:
        raise ValueError(f"No agent found for focus_area '{focus_area}'")
    
    # Create the autofix scanner for this focus area
    agent_config = agents_config['agents'][agent_id]
    settings = agents_config.get('settings', {})
    scanner = AutoFixScanner(
        focus_area=focus_area,
        agent_config=agent_config,
        model_manager=model_manager,
        settings=settings,
        repo_root=repo_root
    )
    
    logger.info(f"   Using scanner: {scanner.name}")
    
    decider = AutoFixDecider()
    fixer = CodeFixGenerator(model_manager)
    
    # Discover files from repository root
    logger.info(f"\n🔍 Discovering files in {repo_root}...")
    files_to_scan = discover_files(repo_root, file_patterns)
    
    # Limit files to control costs
    files_to_scan = files_to_scan[:20]
    
    logger.info(f"   Found {len(files_to_scan)} files to scan")
    
    # Process each file
    for idx, file_path in enumerate(files_to_scan, 1):
        if len(fixes) >= max_prs:
            logger.info(f"\n✋ Reached max PRs limit ({max_prs})")
            break
        
        # Get relative path for display
        try:
            relative_path = file_path.relative_to(repo_root)
        except ValueError:
            relative_path = file_path
        
        logger.info(f"\n[{idx}/{len(files_to_scan)}] Scanning: {relative_path}")
        
        try:
            # Check file size before reading to avoid memory issues
            file_size = file_path.stat().st_size
            if file_size > MAX_FILE_SIZE_BYTES:
                logger.warning(f"   ⏭️  Skipping: File too large ({file_size / 1024:.1f} KB > {MAX_FILE_SIZE_BYTES / 1024:.0f} KB)")
                continue
            
            # Read file using absolute path
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Scan with autofix scanner (NOT PR review system)
            logger.info(f"   Scanning with {scanner.name}...")
            
            scan_result = scanner.scan_file(str(relative_path), content)
            
            if not scan_result.issues:
                continue
            
            logger.info(f"   {scanner.name}: {len(scan_result.issues)} issue(s)")
            
            for issue in scan_result.issues:
                if len(fixes) >= max_prs:
                    break
                
                # Should we fix this?
                issue_dict = {
                    'severity': issue.severity.value,
                    'category': issue.category,
                    'description': issue.description,
                    'line_number': issue.line_number,
                    'suggestion': issue.suggestion
                }
                
                should_fix, reason = decider.should_auto_fix(
                    issue_dict,
                    scanner.name
                )
                
                if should_fix:
                    logger.info(f"   ✅ Will fix: {issue.description[:60]}")
                    logger.info(f"      Reason: {reason}")
                    
                    # Generate fix (use relative path for display)
                    logger.info(f"      Generating fix...")
                    fixed_content = fixer.generate_fix(
                        str(relative_path),
                        issue_dict,
                        content
                    )
                    
                    if fixed_content and fixed_content != content:
                        # Create unique ID for this fix (use relative path for consistency)
                        fix_id = hashlib.md5(
                            f"{relative_path}{issue.description}".encode()
                        ).hexdigest()[:8]
                        
                        fixes.append({
                            'id': fix_id,
                            'title': f"{issue.category}: {issue.description[:60]}",
                            'body': format_pr_body(issue, scan_result, str(relative_path), reason),
                            'severity': issue.severity.value,
                            'agent': scanner.name,
                            'files': [{
                                'path': str(relative_path),
                                'content': fixed_content
                            }]
                        })
                        
                        logger.info(f"      ✓ Fix generated")
                        
                        # Don't try to fix more issues in this file
                        break
                    else:
                        logger.warning(f"      ✗ Fix failed or no changes")
                else:
                    logger.info(f"   ⏭️  Skipping: {reason}")
        
        except FileNotFoundError as e:
            logger.warning(f"   ✗ File not found: {e}")
            continue
        except PermissionError as e:
            logger.warning(f"   ✗ Permission denied: {e}")
            continue
        except UnicodeDecodeError as e:
            logger.warning(f"   ✗ File encoding error (not UTF-8): {e}")
            continue
        except ValueError as e:
            logger.warning(f"   ✗ Invalid input: {e}")
            continue
        except Exception as e:
            logger.error(f"   ✗ Unexpected error processing {relative_path}: {type(e).__name__}: {e}")
            # Log but continue - don't fail entire run for one file
            continue
    
    return fixes

