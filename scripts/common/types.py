"""
Shared data structures used by both PR review and autofix systems
"""
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


class ReviewDecision(Enum):
    """Master agent decision types"""
    APPROVE = "APPROVE"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    DEFER_TO_HUMAN = "DEFER_TO_HUMAN"


class IssueSeverity(Enum):
    """Issue severity levels"""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


@dataclass
class ReviewIssue:
    """Represents a single review issue"""
    severity: IssueSeverity
    category: str
    description: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    suggestion: Optional[str] = None
    code_snippet: Optional[str] = None


@dataclass
class AgentReview:
    """Review from a single agent"""
    agent_name: str
    agent_role: str
    issues: List[ReviewIssue]
    summary: str
    model_used: str
    timestamp: str


@dataclass
class MasterReview:
    """Final review from master agent"""
    decision: ReviewDecision
    reasoning: str
    agent_reviews: List[AgentReview]
    critical_issues_count: int
    high_issues_count: int
    recommendations: List[str]
    model_used: str
    timestamp: str

