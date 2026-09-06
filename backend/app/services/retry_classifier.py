"""Deterministic failure classification for P1-6 retry semantics.

Classifies execution failures into retry categories with explicit,
bounded retry policies. Prevents retry of authorization failures,
unknown tools, and permanent failures.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


# Retry category constants
TRANSIENT = "TRANSIENT"
VALIDATION = "VALIDATION"
AUTHORIZATION = "AUTHORIZATION"
APPROVAL = "APPROVAL"
MISSING_INPUT = "MISSING_INPUT"
TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
EXECUTION = "EXECUTION"
PERMANENT = "PERMANENT"

VALID_RETRY_CATEGORIES = {
    TRANSIENT,
    VALIDATION,
    AUTHORIZATION,
    APPROVAL,
    MISSING_INPUT,
    TOOL_NOT_FOUND,
    EXECUTION,
    PERMANENT,
}

# Categories that are safe to retry
RETRYABLE_CATEGORIES = {TRANSIENT, VALIDATION, EXECUTION}

# Categories that require human input / approval (stop execution)
HUMAN_WAIT_CATEGORIES = {APPROVAL, MISSING_INPUT}

# Categories that must never be retried
NON_RETRYABLE_CATEGORIES = {AUTHORIZATION, TOOL_NOT_FOUND, PERMANENT}


# Pattern-based classification rules
_TRANSIENT_PATTERNS = [
    re.compile(r"timeout", re.IGNORECASE),
    re.compile(r"connection", re.IGNORECASE),
    re.compile(r"network", re.IGNORECASE),
    re.compile(r"temporarily", re.IGNORECASE),
    re.compile(r"unavailable", re.IGNORECASE),
    re.compile(r"503", re.IGNORECASE),
    re.compile(r"502", re.IGNORECASE),
    re.compile(r"500", re.IGNORECASE),
    re.compile(r"resource.*busy", re.IGNORECASE),
    re.compile(r"deadlock", re.IGNORECASE),
]

_AUTHORIZATION_PATTERNS = [
    re.compile(r"unauthorized", re.IGNORECASE),
    re.compile(r"forbidden", re.IGNORECASE),
    re.compile(r"403", re.IGNORECASE),
    re.compile(r"permission", re.IGNORECASE),
    re.compile(r"access denied", re.IGNORECASE),
    re.compile(r"authentication", re.IGNORECASE),
    re.compile(r"invalid token", re.IGNORECASE),
    re.compile(r"expired token", re.IGNORECASE),
]

_TOOL_NOT_FOUND_PATTERNS = [
    re.compile(r"tool not found", re.IGNORECASE),
    re.compile(r"unknown tool", re.IGNORECASE),
    re.compile(r"unsupported action", re.IGNORECASE),
    re.compile(r"unrecognized action", re.IGNORECASE),
    re.compile(r"invalid action", re.IGNORECASE),
]

_PERMANENT_PATTERNS = [
    re.compile(r"not found", re.IGNORECASE),
    re.compile(r"does not exist", re.IGNORECASE),
    re.compile(r"already exists", re.IGNORECASE),
    re.compile(r"constraint.*violation", re.IGNORECASE),
    re.compile(r"unique.*violation", re.IGNORECASE),
    re.compile(r"invalid.*format", re.IGNORECASE),
    re.compile(r"malformed", re.IGNORECASE),
]

_MISSING_INPUT_PATTERNS = [
    re.compile(r"missing", re.IGNORECASE),
    re.compile(r"required", re.IGNORECASE),
    re.compile(r"input", re.IGNORECASE),
]

_EXECUTION_PATTERNS = [
    re.compile(r"execution failed", re.IGNORECASE),
    re.compile(r"internal error", re.IGNORECASE),
    re.compile(r"runtime error", re.IGNORECASE),
]


@dataclass
class RetryDecision:
    """Decision about how to handle a failure."""

    category: str
    retryable: bool
    human_wait: bool
    max_retries: int
    backoff_seconds: float


def classify_failure(
    error_message: str | None,
    *,
    context: dict[str, Any] | None = None,
) -> RetryDecision:
    """Classify a failure into a retry category.

    Args:
        error_message: The error message or description.
        context: Optional context dict (e.g., action_type, tool_name, step_name).

    Returns:
        RetryDecision with category, retryability, and policy.
    """
    message = (error_message or "").strip().lower()
    if not message:
        return RetryDecision(
            category=TRANSIENT,
            retryable=True,
            human_wait=False,
            max_retries=3,
            backoff_seconds=1.0,
        )

    # Check authorization patterns first (highest priority)
    for pattern in _AUTHORIZATION_PATTERNS:
        if pattern.search(message):
            return RetryDecision(
                category=AUTHORIZATION,
                retryable=False,
                human_wait=False,
                max_retries=0,
                backoff_seconds=0.0,
            )

    # Check tool not found patterns
    for pattern in _TOOL_NOT_FOUND_PATTERNS:
        if pattern.search(message):
            return RetryDecision(
                category=TOOL_NOT_FOUND,
                retryable=False,
                human_wait=False,
                max_retries=0,
                backoff_seconds=0.0,
            )

    # Check permanent patterns
    for pattern in _PERMANENT_PATTERNS:
        if pattern.search(message):
            return RetryDecision(
                category=PERMANENT,
                retryable=False,
                human_wait=False,
                max_retries=0,
                backoff_seconds=0.0,
            )

    # Check missing input patterns
    for pattern in _MISSING_INPUT_PATTERNS:
        if pattern.search(message):
            return RetryDecision(
                category=MISSING_INPUT,
                retryable=False,
                human_wait=True,
                max_retries=0,
                backoff_seconds=0.0,
            )

    # Check execution patterns
    for pattern in _EXECUTION_PATTERNS:
        if pattern.search(message):
            return RetryDecision(
                category=EXECUTION,
                retryable=True,
                human_wait=False,
                max_retries=3,
                backoff_seconds=2.0,
            )

    # Check transient patterns
    for pattern in _TRANSIENT_PATTERNS:
        if pattern.search(message):
            return RetryDecision(
                category=TRANSIENT,
                retryable=True,
                human_wait=False,
                max_retries=3,
                backoff_seconds=2.0,
            )

    # Default: classify based on context
    ctx_action = (context or {}).get("action_type", "")
    ctx_tool = (context or {}).get("tool_name", "")

    if "approval" in ctx_action.lower() or "approval" in ctx_tool.lower():
        return RetryDecision(
            category=APPROVAL,
            retryable=False,
            human_wait=True,
            max_retries=0,
            backoff_seconds=0.0,
        )

    # Default to transient for unknown errors (safe default)
    return RetryDecision(
        category=TRANSIENT,
        retryable=True,
        human_wait=False,
        max_retries=3,
        backoff_seconds=1.0,
    )


def is_retryable(category: str) -> bool:
    """Check if a retry category is safe to retry.

    Args:
        category: Retry category string.

    Returns:
        True if the category is retryable.
    """
    return category in RETRYABLE_CATEGORIES


def requires_human_wait(category: str) -> bool:
    """Check if a retry category requires human input/approval.

    Args:
        category: Retry category string.

    Returns:
        True if human input or approval is required.
    """
    return category in HUMAN_WAIT_CATEGORIES


def should_never_retry(category: str) -> bool:
    """Check if a retry category must never be retried.

    Args:
        category: Retry category string.

    Returns:
        True if the category must never be retried.
    """
    return category in NON_RETRYABLE_CATEGORIES


# Bounded retry policy: max total retries per execution
MAX_EXECUTION_RETRIES = 5

# Bounded retry policy: max retries per step
MAX_STEP_RETRIES = 3


class BoundedRetryPolicy:
    """Bounded retry policy for execution and step retries.

    Prevents infinite retry loops by enforcing explicit bounds.
    """

    def __init__(
        self,
        max_execution_retries: int = MAX_EXECUTION_RETRIES,
        max_step_retries: int = MAX_STEP_RETRIES,
    ) -> None:
        """Initialize the retry policy.

        Args:
            max_execution_retries: Maximum total retries per execution.
            max_step_retries: Maximum retries per individual step.
        """
        self._max_execution_retries = max_execution_retries
        self._max_step_retries = max_step_retries

    @property
    def max_execution_retries(self) -> int:
        """Maximum total retries per execution."""
        return self._max_execution_retries

    @property
    def max_step_retries(self) -> int:
        """Maximum retries per individual step."""
        return self._max_step_retries

    def can_retry_execution(self, current_retry_count: int) -> bool:
        """Check if the execution can be retried.

        Args:
            current_retry_count: Current number of retries.

        Returns:
            True if retry is allowed within bounds.
        """
        return current_retry_count < self._max_execution_retries

    def can_retry_step(self, attempt_index: int) -> bool:
        """Check if a step can be retried.

        Args:
            attempt_index: Current attempt index (0-based).

        Returns:
            True if retry is allowed within bounds.
        """
        return attempt_index < self._max_step_retries

    def next_backoff(self, attempt_index: int, base_seconds: float = 1.0) -> float:
        """Calculate backoff for the next retry attempt.

        Uses exponential backoff: base * 2^attempt_index.

        Args:
            attempt_index: Current attempt index (0-based).
            base_seconds: Base backoff in seconds.

        Returns:
            Backoff in seconds.
        """
        return base_seconds * (2 ** attempt_index)