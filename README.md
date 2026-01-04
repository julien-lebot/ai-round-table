# AI Code Review System

Automated PR reviews using multiple specialized AI agents. The AI actually submits GitHub PR reviews (approve/request changes), not just comments.

## Setup

1. Add API keys to GitHub Secrets (need at least one):
   - `ANTHROPIC_API_KEY`
   - `OPENAI_API_KEY`
   - `GLM_API_KEY`

2. That's it. Open a PR and get a review.

## How It Works

**5 specialist agents** review code in parallel:
- Security (vulnerabilities, auth, injection)
- Architecture (design patterns, SOLID, scalability)
- Performance (complexity, queries, caching)
- Testing (coverage, edge cases, quality)
- Style (conventions, documentation, readability)

**Master agent** synthesizes their feedback and makes a decision:
- `APPROVE` → PR gets approved, can auto-merge
- `REQUEST_CHANGES` → Blocks merging until fixed
- `DEFER_TO_HUMAN` → Just comments, no approval/block

The AI submits a real GitHub review via the API, so it shows up as an actual approval in the PR UI.

## Auto-Merge

Add the `merge-when-ready` label to a PR. Once:
- AI approves (actual review, not just label)
- All CI checks pass
- No merge conflicts

It auto-merges to main/master.

## Configuration

### Models (`config/models.yaml`)

Define available models and their settings:

```yaml
models:
  glm_4:
    provider: glm
    model: glm-4
    api_key_env: GLM_API_KEY
    
  claude_sonnet:
    provider: anthropic
    model: claude-3-5-sonnet-20241022
    api_key_env: ANTHROPIC_API_KEY
```

### Agents (`config/agents.yaml`)

**Each agent specifies its own model preference order**:

```yaml
agents:
  security:
    models: 
      - claude_sonnet      # Try this first
      - openai_gpt4        # Then this
      - glm_4              # Finally this
    
  style:
    models:
      - glm_4              # Cheaper model is fine for style
      - openai_gpt35
```

**How it works:**
1. Agent tries its first model
2. If unavailable or fails → tries second model
3. Continues down the list until success
4. Each agent can have different model preferences

**Model Tiering Strategy:**
- **Critical agents** (Master, Security, Architecture): Start with best models
  - Claude Sonnet (best quality)
  - GLM-4.7 (deep reasoning, slower)
  - GPT-4 (backup)
- **Analysis agent** (Performance): Balanced models
  - Claude Sonnet
  - GLM-4.5 (balanced speed/quality)
- **Simple agents** (Testing, Style): Fast, cheap models
  - GLM-4-Plus (fastest, high concurrency)
  - GLM-4.5 (fallback)
  - GPT-3.5 (backup)

GLM models are free tier, so they're prioritized to minimize costs.

## Customization

**Change approval behavior** - Edit `.github/ai-review/scripts/review/review_pr.py`:

```python
# Line ~175: Make AI never approve (only comment)
event_map = {
    ReviewDecision.APPROVE: 'COMMENT',  # Changed from 'APPROVE'
    ReviewDecision.REQUEST_CHANGES: 'COMMENT',
    ReviewDecision.DEFER_TO_HUMAN: 'COMMENT'
}
```

**Skip files** - Edit `config/agents.yaml`:

```yaml
settings:
  skip_patterns:
    - "*.lock"
    - "node_modules/**"
    - "dist/**"
```

**Change merge strategy** - Edit `.github/workflows/auto-merge.yml` line ~160:

```yaml
merge_method: 'squash'  # or 'merge' or 'rebase'
```

## Branch Protection

If you want the AI approval to count toward branch protection:

1. Settings → Branches → Add rule for `main`
2. Enable "Require pull request reviews before merging"
3. Set "Required approving reviews: 1"
4. The AI approval counts as that 1 review

For human oversight, set required reviews to 2+ (AI + humans).

## Local Testing

### PR Review (dry run)

```bash
# Install dependencies
pip install -r .github/ai-review/requirements.txt

# Set API key
export ANTHROPIC_API_KEY="your-key"

# Dry run (doesn't post to GitHub)
cd .github/ai-review/scripts
python review/review_pr.py --dry-run
```

### Auto-Fix Bot

```bash
# From repository root
cd .github/ai-review/scripts

# Set API keys (at least one)
export ANTHROPIC_API_KEY="your-key"
export OPENAI_API_KEY="your-key"
export GLM_API_KEY="your-key"

# Run auto-fix bot
python -m autofix.autofix_bot \
  --focus-area style \
  --max-prs 3 \
  --file-patterns "*.cs,*.py" \
  --output fixes.json

# Review generated fixes
cat fixes.json | jq '.'
```

**Note:** The auto-fix bot scans files and generates fixes locally in `fixes.json`. It does NOT create PRs - only the GitHub Actions workflow creates PRs.

## File Structure

```
.github/
├── ai-review/
│   ├── config/
│   │   ├── models.yaml        # Model configs
│   │   └── agents.yaml        # Agent configs
│   ├── scripts/
│   │   ├── model_manager.py   # Provider abstraction + fallback
│   │   ├── agents.py          # Agent implementation
│   │   ├── review_pr.py       # Main script (called by workflow)
│   │   └── setup.py           # Validation script
│   └── requirements.txt
└── workflows/
    ├── ai-review.yml          # Review workflow
    └── auto-merge.yml         # Auto-merge workflow
```

## Troubleshooting

**Review not posting?**
- Check workflow logs in Actions tab
- Verify at least one API key is set
- Check model names in config match providers

**Auto-merge not working?**
- Ensure `merge-when-ready` label is added
- Check that AI submitted an APPROVED review (not just comment)
- Verify all CI checks pass
- Check for merge conflicts

**All models failing?**
- Verify API keys are correct
- Check you have quota/credits remaining
- Try setting one model's priority to 1

## Notes

- The AI runs as `github-actions[bot]`
- Humans can dismiss/override AI reviews
- Review artifacts kept for 30 days
- Costs depend on PR size and model used (typically $0.01-0.10 per review)
