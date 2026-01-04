# AGENTS.md

Instructions for AI coding agents working on the AI Code Review System Python project.

## Setup commands

- Install dependencies: `pip install -r requirements.txt`
- For development with tests: `pip install -r requirements.txt pytest pytest-asyncio`
- Set up environment variables (copy from `env.example`):
  - `ANTHROPIC_API_KEY` - For Claude models
  - `OPENAI_API_KEY` - For OpenAI models
  - `GLM_API_KEY` - For GLM/Zhipu models
  - `GITHUB_TOKEN` - For GitHub API (auto-provided in Actions)

## Build commands

- No build step required (Python interpreted language)
- Validate configuration: `python scripts/common/setup.py`
- Check imports: `python -m py_compile scripts/**/*.py`

## Test commands

- Run all tests: `pytest .github/ai-review/scripts/`
- Run specific test file: `pytest .github/ai-review/scripts/review/tests/test_review_pr.py`
- Run with verbose output: `pytest -v`
- Run with coverage: `pytest --cov=scripts --cov-report=html`
- Run async tests: `pytest -v` (pytest-asyncio handles async automatically)

## Code style

- Python 3.8+ (use type hints)
- Follow PEP 8 style guide
- Use f-strings for string formatting
- Prefer async/await for I/O operations
- Use dataclasses or TypedDict for structured data
- Type hints required for function parameters and return values
- Use `pathlib.Path` instead of `os.path` where possible

## Project structure

- **scripts/common/** - Shared utilities
  - `model_manager.py` - Provider abstraction and model fallback logic
  - `types.py` - Type definitions
  - `utils.py` - Helper functions
- **scripts/review/** - PR review functionality
  - `agents.py` - Specialized AI agents (Security, Architecture, etc.)
  - `review_pr.py` - Main review script (called by GitHub Actions)
- **scripts/autofix/** - Auto-fix functionality
  - `scanner.py` - Scans PR for fixable issues
  - `fixer.py` - Applies fixes
  - `engine.py` - Orchestrates fix process
- **config/** - Configuration files
  - `models.yaml` - Model definitions and provider settings
  - `agents.yaml` - Agent configurations and model preferences

## Configuration

- Models are defined in `config/models.yaml`
- Agents and their model preferences in `config/agents.yaml`
- Model fallback: Agents try models in order until one succeeds
- Model tiering strategy:
  - Critical agents (Master, Security, Architecture): Start with Claude Sonnet
  - Performance agent: Balanced models
  - Simple agents (Testing, Style): Fast/cheap models (GLM-4-Plus)

## Testing instructions

- Tests use pytest framework
- Mock external API calls (GitHub API, AI providers)
- Test model fallback logic
- Test agent decision-making
- Test error handling and edge cases
- Use `unittest.mock` for mocking
- Async tests use `pytest-asyncio`
- Run tests before committing changes
- Add tests for new agents or features

## Local testing

### PR Review (dry run)
- Dry run (doesn't post to GitHub): `cd .github/ai-review/scripts && python review/review_pr.py --dry-run`
- Set `GITHUB_EVENT_PATH` to point to `test-event.json` for local testing
- Set `GITHUB_REPOSITORY` environment variable for local testing
- Use `--dry-run` flag to test without making API calls

### Auto-Fix Bot
```powershell
# From repository root
cd .github/ai-review/scripts

# Set API keys (at least one)
$env:ANTHROPIC_API_KEY="your-key"
$env:OPENAI_API_KEY="your-key"
$env:GLM_API_KEY="your-key"

# Run auto-fix bot
python -m autofix.autofix_bot `
  --focus-area style `
  --max-prs 3 `
  --file-patterns "*.cs,*.py" `
  --output fixes.json

# Review generated fixes
cat fixes.json | ConvertFrom-Json | ConvertTo-Json -Depth 10
```

The auto-fix bot will scan files, find issues, and generate fixes in `fixes.json`. It does NOT create PRs locally - only the GitHub Actions workflow does that.

## Common patterns

- Use `ModelManager` for all AI provider calls (handles fallback)
- Agents return structured feedback with severity levels
- Master agent synthesizes specialist agent feedback
- Use GitHub API for PR operations (reviews, comments, labels)
- Rate limiting handled in `autofix/rate_limiter.py`
- Error handling should log and continue (don't fail entire review)

## Important files

- `scripts/common/model_manager.py` - Core abstraction for AI providers
- `scripts/review/agents.py` - Agent implementations (843 lines, complex)
- `scripts/review/review_pr.py` - Main entry point for GitHub Actions
- `config/models.yaml` - Model configuration (must match provider names)
- `config/agents.yaml` - Agent configuration (model preferences, skip patterns)

## GitHub Actions integration

- Workflow: `.github/workflows/ai-review.yml`
- Triggered on `pull_request` events
- Reads `GITHUB_EVENT_PATH` for PR information
- Posts actual GitHub reviews (APPROVE/REQUEST_CHANGES/COMMENT)
- Auto-merge workflow: `.github/workflows/auto-merge.yml`

## PR instructions

- Title format: `[AI-Review] <Description>`
- Always run `pytest` before committing
- Ensure all tests pass
- Test locally with `--dry-run` flag before pushing
- Update configuration files if adding new models or agents
- Document any changes to agent behavior or model preferences
- Check that model names in config match actual provider model names

## Security considerations

- Never commit API keys (use environment variables or GitHub Secrets)
- API keys are read from environment variables only
- GitHub token is automatically provided in Actions context
- Validate all user input from GitHub events
- Handle API rate limits gracefully

### Path Traversal Protection

The AutoFixScanner implements comprehensive path traversal protection:

- **Repository Root Validation**: All file paths are validated against the repository root
- **Directory Traversal Prevention**: Paths containing `..` are immediately rejected
- **Absolute Path Validation**: Absolute paths are checked to ensure they're within repository boundaries
- **Symlink Protection**: Symlinks are resolved and validated to prevent escaping the repository

When initializing AutoFixScanner, always pass the `repo_root` parameter:

```python
scanner = AutoFixScanner(
    focus_area='style',
    agent_config=agent_config,
    model_manager=model_manager,
    settings=settings,
    repo_root=Path(repo_root)  # Required for security
)
```

### Circuit Breaker Pattern

The ModelManager implements a circuit breaker pattern to prevent wasted retries within a single run:

- **Purpose**: When scanning multiple files in one run, if a model fails consistently (e.g., out of quota, invalid key), stop trying it to save time
- **Automatic Failure Tracking**: Tracks consecutive failures per model
- **Circuit Opening**: After 3 consecutive failures, the model is temporarily skipped for remaining files
- **Automatic Recovery**: After 1 minute, the circuit resets and the model is retried (useful for longer runs)
- **Independent Circuits**: Each model has its own circuit breaker state

**Example**: If you're scanning 20 files and Model A fails on the first 3 files due to rate limiting, the circuit breaker will skip Model A for the remaining 17 files and immediately try the fallback model instead of wasting 3 retries × 17 files = 51 failed attempts.

### Performance Optimizations

- **File Size Checks**: Files are checked for size BEFORE reading into memory
- **Maximum File Size**: Files > 20KB are automatically skipped (configurable via `MAX_FILE_SIZE_BYTES`)
- **Memory-Efficient Scanning**: Static analysis is used for files > 20KB to avoid LLM costs

### Error Handling Best Practices

- **Fail-Fast for Security**: Path validation and security issues raise exceptions immediately
- **Graceful Degradation for Processing**: Parsing and API errors are logged but allow processing to continue
- **Comprehensive Logging**: All errors are logged with appropriate severity levels
- **Sanitized Error Messages**: Error messages are sanitized to prevent information leakage

