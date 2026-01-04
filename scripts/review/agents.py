#!/usr/bin/env python3
"""
AI Code Review Agents
Specialized agents that review code in parallel
"""
import os
import json
import re
from typing import Dict, List, Optional, Any
from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import yaml
import jsonschema
from common.model_manager import ModelManager
from common.types import (
    ReviewDecision, IssueSeverity, ReviewIssue,
    AgentReview, MasterReview
)

# Pre-compiled regex patterns for sanitization (performance optimization)
_SANITIZE_PATTERNS = [
    re.compile(r'^(ignore|forget|override|disregard).*(previous|above|instructions|system|prompt)', re.IGNORECASE),
    re.compile(r'^(you are|act as|pretend to be|roleplay as)', re.IGNORECASE),
    re.compile(r'^(system|assistant|user):', re.IGNORECASE),
    re.compile(r'<\|(system|assistant|user)\|>', re.IGNORECASE),
]

# Memory and size limits for diff processing
# These limits prevent excessive memory usage when processing large PRs
MAX_DIFF_SIZE_BYTES = int(os.getenv('MAX_DIFF_SIZE_BYTES', 50 * 1024 * 1024))  # 50MB default
MAX_DIFF_SIZE_PER_AGENT = int(os.getenv('MAX_DIFF_SIZE_PER_AGENT', 50000))  # 50KB per agent
MAX_GLOBAL_MEMORY_MB = int(os.getenv('MAX_GLOBAL_MEMORY_MB', 200))  # 200MB global limit


def get_memory_usage_mb() -> float:
    """Get current memory usage in MB"""
    try:
        import psutil
        process = psutil.Process(os.getpid())
        return process.memory_info().rss / (1024 * 1024)
    except ImportError:
        # psutil not available, return 0 (will skip memory checks)
        return 0.0
    except Exception:
        return 0.0


def check_memory_limit() -> bool:
    """Check if we're within global memory limits"""
    if MAX_GLOBAL_MEMORY_MB <= 0:
        return True  # No limit set
    
    current_mb = get_memory_usage_mb()
    if current_mb > MAX_GLOBAL_MEMORY_MB:
        import sys
        print(f"⚠️  Memory usage ({current_mb:.1f}MB) exceeds limit ({MAX_GLOBAL_MEMORY_MB}MB)")
        sys.stdout.flush()
        return False
    return True


def split_diff_by_files(diff: str) -> List[tuple[str, str]]:
    """
    Split a diff into per-file chunks.
    Returns list of (file_path, file_diff) tuples.
    """
    if not diff:
        return []
    
    # Pattern to match diff file headers: "diff --git a/path b/path" or "--- a/path" / "+++ b/path"
    file_pattern = re.compile(r'^(?:diff --git|---|\+\+\+)')
    current_file = None
    current_diff = []
    file_diffs = []
    
    lines = diff.split('\n')
    for line in lines:
        # Check if this is a file header
        if file_pattern.match(line):
            # Save previous file if exists
            if current_file and current_diff:
                file_diffs.append((current_file, '\n'.join(current_diff)))
            
            # Extract file path from header
            if line.startswith('diff --git'):
                # Format: "diff --git a/path/to/file b/path/to/file"
                parts = line.split()
                if len(parts) >= 4:
                    current_file = parts[3]  # b/path/to/file (new file path)
                else:
                    current_file = 'unknown'
            elif line.startswith('+++'):
                # Format: "+++ b/path/to/file"
                parts = line.split()
                if len(parts) >= 2:
                    current_file = parts[1].lstrip('b/')
                else:
                    current_file = 'unknown'
            elif line.startswith('---'):
                # Format: "--- a/path/to/file" (old file, but we prefer +++)
                if not current_file:
                    parts = line.split()
                    if len(parts) >= 2:
                        current_file = parts[1].lstrip('a/')
            
            current_diff = [line]
        else:
            if current_file:
                current_diff.append(line)
            else:
                # No file header yet, start with unknown file
                if not current_file:
                    current_file = 'unknown'
                    current_diff = [line]
                else:
                    current_diff.append(line)
    
    # Save last file
    if current_file and current_diff:
        file_diffs.append((current_file, '\n'.join(current_diff)))
    
    return file_diffs if file_diffs else [('unknown', diff)]


def preprocess_diff(diff: str, max_size: int = MAX_DIFF_SIZE_PER_AGENT) -> tuple[str, bool, int, int]:
    """
    Pre-process diff: sanitize, truncate, and optionally chunk.
    
    Returns:
        tuple: (processed_diff, was_truncated, lines_removed, files_included)
    """
    if not diff:
        return "", False, 0, 0
    
    # Check initial size
    original_size = len(diff)
    
    # Check global memory limit
    if not check_memory_limit():
        import sys
        print(f"⚠️  Approaching memory limit, truncating diff from {original_size} to {max_size} bytes")
        sys.stdout.flush()
    
    # Sanitize first
    sanitized, was_truncated, lines_removed = sanitize_input(diff, max_length=max_size)
    
    # If still too large after sanitization, truncate more aggressively
    if len(sanitized) > max_size:
        sanitized = sanitized[:max_size] + "\n[... truncated due to size limit ...]"
        was_truncated = True
    
    # Count files in the processed diff
    file_diffs = split_diff_by_files(sanitized)
    files_included = len(file_diffs)
    
    return sanitized, was_truncated, lines_removed, files_included


def sanitize_input(text: str, max_length: int = 10000) -> tuple[str, bool, int]:
    """
    Sanitize user input to prevent prompt injection attacks.
    Removes or neutralizes potentially dangerous patterns.
    
    Optimized for single-pass processing with combined pattern checking.
    
    Returns:
        tuple: (sanitized_text, was_truncated, lines_removed)
    """
    if not text:
        return "", False, 0
    
    was_truncated = False
    lines_removed = 0
    
    # Truncate to max length first
    if len(text) > max_length:
        text = text[:max_length] + "\n[... truncated ...]"
        was_truncated = True
    
    # Remove common injection patterns using pre-compiled regex
    # Optimized: single pass through lines, check all patterns at once
    lines = text.split('\n')
    sanitized_lines = []
    
    for line in lines:
        # Check if line matches dangerous patterns using pre-compiled regex
        # any() short-circuits on first match, making this efficient
        is_dangerous = any(pattern.search(line) for pattern in _SANITIZE_PATTERNS)
        if not is_dangerous:
            sanitized_lines.append(line)
        else:
            lines_removed += 1
    
    sanitized_text = '\n'.join(sanitized_lines)
    return sanitized_text, was_truncated, lines_removed


# JSON schema for agent review responses
_AGENT_REVIEW_SCHEMA = {
    "type": "object",
    "required": ["summary"],
    "properties": {
        "summary": {"type": "string"},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["severity", "description"],
                "properties": {
                    "severity": {
                        "type": "string",
                        "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
                    },
                    "category": {"type": "string"},
                    "description": {"type": "string"},
                    "file_path": {"type": ["string", "null"]},
                    "line_number": {"type": ["integer", "null"]},
                    "suggestion": {"type": ["string", "null"]},
                    "code_snippet": {"type": ["string", "null"]}
                }
            }
        }
    }
}

# JSON schema for master agent decision
_MASTER_DECISION_SCHEMA = {
    "type": "object",
    "required": ["decision", "reasoning"],
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["APPROVE", "REQUEST_CHANGES", "DEFER_TO_HUMAN"]
        },
        "reasoning": {"type": "string"},
        "recommendations": {
            "type": "array",
            "items": {"type": "string"}
        }
    }
}


class ReviewAgent:
    """Base class for review agents"""
    
    def __init__(
        self,
        name: str,
        role: str,
        system_prompt: str,
        models: List[str],
        model_manager: ModelManager,
        weight: int = 50
    ):
        self.name = name
        self.role = role
        self.system_prompt = system_prompt
        self.models = models
        self.model_manager = model_manager
        self.weight = weight
    
    def review(
        self, 
        diff: str, 
        file_list: List[str], 
        pr_description: str, 
        preprocessed_diff: Optional[str] = None,
        preprocessed_description: Optional[str] = None
    ) -> AgentReview:
        """Perform code review
        
        Args:
            diff: Original diff (for reference)
            file_list: List of changed files
            pr_description: PR description (for reference, use preprocessed_description if provided)
            preprocessed_diff: Pre-processed and sanitized diff (if provided, used instead of processing diff)
            preprocessed_description: Pre-processed and sanitized description (if provided, used instead of processing)
        """
        
        use_preprocessed = preprocessed_diff is not None
        diff_to_use = preprocessed_diff if use_preprocessed else diff
        desc_to_use = preprocessed_description if preprocessed_description is not None else pr_description
        prompt = self._build_prompt(
            diff_to_use, 
            file_list, 
            desc_to_use, 
            diff_already_processed=use_preprocessed,
            description_already_processed=preprocessed_description is not None
        )
        
        try:
            response, model_used = self.model_manager.generate_with_fallback(
                self.models,
                prompt,
                self.system_prompt
            )
            
            review_data = self._parse_response(response)
            
            return AgentReview(
                agent_name=self.name,
                agent_role=self.role,
                issues=review_data['issues'],
                summary=review_data['summary'],
                model_used=model_used,
                timestamp=self._get_timestamp()
            )
        except ValueError as e:
            # Configuration or validation error
            return AgentReview(
                agent_name=self.name,
                agent_role=self.role,
                issues=[],
                summary=f"Configuration error: {str(e)[:100]}",
                model_used="none",
                timestamp=self._get_timestamp()
            )
        except Exception as e:
            # Other errors - return empty review, master agent will handle it
            return AgentReview(
                agent_name=self.name,
                agent_role=self.role,
                issues=[],
                summary="Agent unavailable",
                model_used="none",
                timestamp=self._get_timestamp()
            )
    
    def _build_prompt(
        self, 
        diff: str, 
        file_list: List[str], 
        pr_description: str, 
        diff_already_processed: bool = False,
        description_already_processed: bool = False
    ) -> str:
        """Build the prompt for the agent
        
        Args:
            diff: Diff string (may already be preprocessed)
            file_list: List of changed files
            pr_description: PR description (may already be preprocessed)
            diff_already_processed: If True, diff is already sanitized/processed, skip processing
            description_already_processed: If True, description is already sanitized/processed, skip processing
        """
        # Only sanitize description if not already preprocessed
        if description_already_processed:
            safe_description = pr_description
            desc_truncated = False
            desc_lines_removed = 0
        else:
            safe_description, desc_truncated, desc_lines_removed = sanitize_input(pr_description, max_length=2000)
        
        # Only process diff if not already preprocessed
        if diff_already_processed:
            safe_diff = diff
            diff_truncated = False
            diff_lines_removed = 0
        else:
            safe_diff, diff_truncated, diff_lines_removed = sanitize_input(diff, max_length=MAX_DIFF_SIZE_PER_AGENT)
        
        # Warn if sanitization occurred (only warn once, during preprocessing in orchestrator)
        # Skip warnings here to avoid duplicate messages when using preprocessed inputs
        
        return f"""
# Code Review Request

## Pull Request Description
{safe_description}

## Files Changed
{', '.join(file_list)}

## Code Diff
```diff
{safe_diff}
```

## Instructions
Please review this code change according to your specialization.

**CRITICAL GUIDELINES:**
- Only report CRITICAL, HIGH, or MEDIUM severity issues
- DO NOT report LOW or INFO issues (trivial things handled by linters/auto-fix)
- Only include line_number if you can determine it accurately from the diff
- If line number is uncertain, omit it (issue will go in summary comment)
- Focus on issues that require human judgment, not automated fixes

Return your review in the following JSON format:
{{
    "summary": "Brief summary of your review",
    "issues": [
        {{
            "severity": "CRITICAL|HIGH|MEDIUM",
            "category": "Category of the issue",
            "description": "Description of the issue",
            "file_path": "path/to/file.py",
            "line_number": 42,  # ONLY if you can determine it accurately from diff
            "suggestion": "How to fix it",
            "code_snippet": "Optional code snippet"
        }}
    ]
}}

**IMPORTANT for line_number:**
- Use the line number from the NEW file (after changes) as shown in the diff
- Look for lines starting with "+" in the diff to find new/changed lines
- The line number should match the line in the final file (not diff-relative)
- If you cannot determine the exact line number reliably, OMIT the line_number field
- Line numbers must be positive integers
- Only include line_number for CRITICAL or HIGH severity issues

Be specific, actionable, and constructive. Focus on important issues only.
"""
    
    def _parse_response(self, response: str) -> Dict[str, Any]:
        """Parse the agent's response"""
        try:
            # Try to extract JSON from the response
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            
            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                try:
                    data = json.loads(json_str)
                except json.JSONDecodeError as e:
                    # JSON parsing failed - return plain text summary
                    return {
                        'summary': response[:500],
                        'issues': []
                    }
                
                # Validate JSON schema
                try:
                    jsonschema.validate(instance=data, schema=_AGENT_REVIEW_SCHEMA)
                except jsonschema.ValidationError as e:
                    # Schema validation failed - return safe fallback
                    return {
                        'summary': data.get('summary', response[:500]) if isinstance(data, dict) else response[:500],
                        'issues': []
                    }
                
                # Convert issue dicts to ReviewIssue objects with validation
                issues = []
                for issue_dict in data.get('issues', []):
                    # Validate severity enum
                    severity_str = issue_dict.get('severity', 'INFO')
                    if severity_str not in [s.value for s in IssueSeverity]:
                        severity_str = 'INFO'  # Default to INFO for invalid values
                    
                    try:
                        issues.append(ReviewIssue(
                            severity=IssueSeverity[severity_str],
                            category=issue_dict.get('category', 'General'),
                            description=issue_dict.get('description', ''),
                            file_path=issue_dict.get('file_path'),
                            line_number=issue_dict.get('line_number'),
                            suggestion=issue_dict.get('suggestion'),
                            code_snippet=issue_dict.get('code_snippet')
                        ))
                    except (KeyError, ValueError) as e:
                        # Skip invalid issues
                        continue
                
                return {
                    'summary': data.get('summary', 'No summary provided'),
                    'issues': issues
                }
            else:
                # If no JSON found, treat as plain text summary
                return {
                    'summary': response[:1000],  # Limit length
                    'issues': []
                }
        except (ValueError, KeyError) as e:
            # Specific parsing errors
            return {
                'summary': f"Response parsing error: {str(e)[:200]}",
                'issues': []
            }
        except Exception as e:
            # Unexpected errors
            return {
                'summary': response[:500] if response else "Failed to parse response",
                'issues': []
            }
    
    def _get_timestamp(self) -> str:
        """Get current timestamp"""
        from datetime import datetime
        return datetime.utcnow().isoformat() + 'Z'


class MasterAgent(ReviewAgent):
    """Master agent that synthesizes reviews and makes final decisions"""
    
    def __init__(
        self,
        name: str,
        system_prompt: str,
        models: List[str],
        model_manager: ModelManager
    ):
        super().__init__(name, "master", system_prompt, models, model_manager, 100)
    
    def synthesize(
        self,
        agent_reviews: List[AgentReview],
        pr_description: str
    ) -> MasterReview:
        """Synthesize all agent reviews and make final decision"""
        
        prompt = self._build_synthesis_prompt(agent_reviews, pr_description)
        
        try:
            response, model_used = self.model_manager.generate_with_fallback(
                self.models,
                prompt,
                self.system_prompt
            )
            
            decision_data = self._parse_decision(response)
            
            # Count issues by severity
            critical_count = sum(
                len([i for i in r.issues if i.severity == IssueSeverity.CRITICAL])
                for r in agent_reviews
            )
            high_count = sum(
                len([i for i in r.issues if i.severity == IssueSeverity.HIGH])
                for r in agent_reviews
            )
            
            return MasterReview(
                decision=decision_data['decision'],
                reasoning=decision_data['reasoning'],
                agent_reviews=agent_reviews,
                critical_issues_count=critical_count,
                high_issues_count=high_count,
                recommendations=decision_data['recommendations'],
                model_used=model_used,
                timestamp=self._get_timestamp()
            )
        except Exception as e:
            # Only show error if ALL models failed completely
            return MasterReview(
                decision=ReviewDecision.DEFER_TO_HUMAN,
                reasoning="Unable to complete automated review. Please review manually.",
                agent_reviews=agent_reviews,
                critical_issues_count=0,
                high_issues_count=0,
                recommendations=["Manual review required"],
                model_used="none",
                timestamp=self._get_timestamp()
            )
    
    def _build_synthesis_prompt(
        self,
        agent_reviews: List[AgentReview],
        pr_description: str
    ) -> str:
        """Build prompt for synthesis"""
        
        reviews_text = []
        for review in agent_reviews:
            issues_text = "\n".join([
                f"  - [{i.severity.value}] {i.description}"
                for i in review.issues
            ])
            reviews_text.append(f"""
## {review.agent_name}
Summary: {review.summary}
Issues found: {len(review.issues)}
{issues_text if issues_text else '  No issues found'}
""")
        
        return f"""
# Master Code Review Synthesis

## Pull Request Description
{pr_description}

## Agent Reviews
{''.join(reviews_text)}

## Your Task
Synthesize the above reviews and make a final decision.

Return your decision in the following JSON format:
{{
    "decision": "APPROVE|REQUEST_CHANGES|DEFER_TO_HUMAN",
    "reasoning": "Detailed explanation of your decision",
    "recommendations": [
        "Specific recommendation 1",
        "Specific recommendation 2"
    ]
}}

Decision Guidelines:
- APPROVE: No critical/high issues, or only minor issues that don't block merge
- REQUEST_CHANGES: Critical or high severity issues that must be addressed
- DEFER_TO_HUMAN: Complex decisions, controversial changes, or unclear situations
"""
    
    def _parse_decision(self, response: str) -> Dict[str, Any]:
        """Parse master agent decision"""
        try:
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            
            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                try:
                    data = json.loads(json_str)
                except json.JSONDecodeError:
                    return {
                        'decision': ReviewDecision.DEFER_TO_HUMAN,
                        'reasoning': response[:500],
                        'recommendations': []
                    }
                
                # Validate JSON schema
                try:
                    jsonschema.validate(instance=data, schema=_MASTER_DECISION_SCHEMA)
                except jsonschema.ValidationError:
                    # Schema validation failed - default to defer
                    return {
                        'decision': ReviewDecision.DEFER_TO_HUMAN,
                        'reasoning': data.get('reasoning', response[:500]) if isinstance(data, dict) else response[:500],
                        'recommendations': data.get('recommendations', []) if isinstance(data, dict) else []
                    }
                
                # Validate decision enum
                decision_str = data.get('decision', 'DEFER_TO_HUMAN')
                if decision_str not in [d.value for d in ReviewDecision]:
                    decision_str = 'DEFER_TO_HUMAN'
                
                return {
                    'decision': ReviewDecision[decision_str],
                    'reasoning': data.get('reasoning', 'No reasoning provided'),
                    'recommendations': data.get('recommendations', [])
                }
            else:
                # Default to defer if can't parse
                return {
                    'decision': ReviewDecision.DEFER_TO_HUMAN,
                    'reasoning': response[:500],
                    'recommendations': []
                }
        except Exception as e:
            print(f"⚠️  Failed to parse decision: {str(e)}")
            return {
                'decision': ReviewDecision.DEFER_TO_HUMAN,
                'reasoning': f"Failed to parse: {response[:200]}",
                'recommendations': []
            }


class AgentOrchestrator:
    """Orchestrates multiple agents to perform code reviews"""
    
    def __init__(self, agents_config_path: str, models_config_path: str):
        with open(agents_config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.model_manager = ModelManager(models_config_path)
        self.agents: List[ReviewAgent] = []
        self.master_agent: Optional[MasterAgent] = None
        
        self._initialize_agents()
    
    def _initialize_agents(self):
        """Initialize all agents from configuration"""
        agents_config = self.config['agents']
        
        for agent_id, agent_config in agents_config.items():
            if agent_config['role'] == 'master':
                self.master_agent = MasterAgent(
                    name=agent_config['name'],
                    system_prompt=agent_config['system_prompt'],
                    models=agent_config['models'],
                    model_manager=self.model_manager
                )
            else:
                agent = ReviewAgent(
                    name=agent_config['name'],
                    role=agent_config['role'],
                    system_prompt=agent_config['system_prompt'],
                    models=agent_config['models'],
                    model_manager=self.model_manager,
                    weight=agent_config.get('weight', 50)
                )
                self.agents.append(agent)
    
    def review_pr(
        self,
        diff: str,
        file_list: List[str],
        pr_description: str
    ) -> MasterReview:
        """Perform complete PR review with all agents in parallel"""
        
        import sys
        
        # Early size check - reject extremely large diffs before processing
        diff_size = len(diff)
        if diff_size > MAX_DIFF_SIZE_BYTES:
            print(f"\n⚠️  Diff size ({diff_size} bytes) exceeds maximum ({MAX_DIFF_SIZE_BYTES} bytes)")
            print(f"   Truncating to {MAX_DIFF_SIZE_BYTES} bytes for processing")
            sys.stdout.flush()
            diff = diff[:MAX_DIFF_SIZE_BYTES] + "\n[... diff truncated due to size limit ...]"
        
        # Pre-process inputs once to avoid redundant processing and reduce memory usage
        print(f"\n📋 Pre-processing inputs (diff: {len(diff)} bytes, description: {len(pr_description)} bytes)...")
        sys.stdout.flush()
        
        # Check initial memory
        initial_memory = get_memory_usage_mb()
        if initial_memory > 0:
            print(f"  Memory usage: {initial_memory:.1f}MB")
            sys.stdout.flush()
        
        # Pre-sanitize PR description once (instead of per-agent)
        processed_description, desc_truncated, desc_lines_removed = sanitize_input(pr_description, max_length=2000)
        if desc_truncated or desc_lines_removed > 0:
            msg = f"  ⚠️  PR description sanitized: {desc_lines_removed} lines removed"
            if desc_truncated:
                msg += " (truncated)"
            print(msg)
            sys.stdout.flush()
        
        # Pre-process diff once (sanitize, truncate if needed)
        processed_diff, was_truncated, lines_removed, files_included = preprocess_diff(
            diff, 
            max_size=MAX_DIFF_SIZE_PER_AGENT
        )
        
        if was_truncated or lines_removed > 0:
            print(f"  ⚠️  Diff processed: {lines_removed} lines removed, {files_included} files included")
            if was_truncated:
                print(f"  ⚠️  Diff truncated to {len(processed_diff)} bytes (limit: {MAX_DIFF_SIZE_PER_AGENT})")
            sys.stdout.flush()
        
        # Check memory after processing
        post_process_memory = get_memory_usage_mb()
        if post_process_memory > 0:
            memory_delta = post_process_memory - initial_memory
            print(f"  Memory after processing: {post_process_memory:.1f}MB (+{memory_delta:.1f}MB)")
            sys.stdout.flush()
        
        # Estimate total memory with all agents
        estimated_total = post_process_memory + (len(processed_diff) * len(self.agents) / (1024 * 1024))
        if estimated_total > MAX_GLOBAL_MEMORY_MB and MAX_GLOBAL_MEMORY_MB > 0:
            print(f"  ⚠️  Estimated memory with {len(self.agents)} agents: {estimated_total:.1f}MB")
            sys.stdout.flush()
        
        print(f"\n📋 Running {len(self.agents)} specialist agents in parallel...")
        sys.stdout.flush()
        
        # Run specialist agents in parallel with pre-processed inputs
        agent_reviews = []
        with ThreadPoolExecutor(max_workers=len(self.agents)) as executor:
            # Submit all agent reviews with pre-processed diff and description
            future_to_agent = {
                executor.submit(
                    agent.review, 
                    diff, 
                    file_list, 
                    pr_description, 
                    processed_diff,
                    processed_description
                ): agent
                for agent in self.agents
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_agent):
                agent = future_to_agent[future]
                try:
                    review = future.result()
                    agent_reviews.append(review)
                    if review.model_used != "none":
                        print(f"  ✓ {agent.name}: {len(review.issues)} issues (model: {review.model_used})")
                    else:
                        print(f"  ⚠️  {agent.name}: Unavailable")
                    sys.stdout.flush()
                except Exception as e:
                    print(f"  ✗ {agent.name}: Error - {str(e)[:100]}")
                    sys.stdout.flush()
                    # Add empty review on error
                    from datetime import datetime
                    agent_reviews.append(AgentReview(
                        agent_name=agent.name,
                        agent_role=agent.role,
                        issues=[],
                        summary=f"Error: {str(e)[:100]}",
                        model_used="none",
                        timestamp=datetime.utcnow().isoformat() + 'Z'
                    ))
        
        # Sort reviews to maintain consistent order
        agent_reviews.sort(key=lambda r: next((i for i, a in enumerate(self.agents) if a.name == r.agent_name), 999))
        
        # Master agent synthesizes (use processed description for consistency)
        print(f"\n🎯 Master agent synthesizing reviews...")
        sys.stdout.flush()
        master_review = self.master_agent.synthesize(agent_reviews, processed_description)
        
        # Format decision for display
        decision_text = master_review.decision.value.replace('_', ' ').title()
        print(f"\n✅ Review complete: {decision_text}")
        sys.stdout.flush()
        return master_review


if __name__ == "__main__":
    # Test the orchestrator
    orchestrator = AgentOrchestrator(
        '.github/ai-review/config/agents.yaml',
        '.github/ai-review/config/models.yaml'
    )
    
    # Simulate a simple review
    diff = """
+ def calculate_total(items):
+     total = 0
+     for item in items:
+         total += item.price
+     return total
"""
    
    review = orchestrator.review_pr(
        diff=diff,
        file_list=['src/calculator.py'],
        pr_description="Add function to calculate total"
    )
    
    print(f"\nDecision: {review.decision.value}")
    print(f"Reasoning: {review.reasoning}")

