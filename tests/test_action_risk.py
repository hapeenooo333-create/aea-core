"""Tests for action risk classification in ActionEngine."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.action_engine import ActionEngine, SAFE_ACTIONS, SENSITIVE_ACTIONS


def test_safe_action_classification():
    """Test that safe actions are classified correctly."""
    engine = ActionEngine()

    for action in SAFE_ACTIONS:
        result = engine.classify_action(action)
        assert result["risk_level"] == "safe"
        assert result["requires_approval"] is False


def test_sensitive_action_classification():
    """Test that sensitive actions are classified correctly."""
    engine = ActionEngine()

    for action in SENSITIVE_ACTIONS:
        result = engine.classify_action(action)
        assert result["risk_level"] == "sensitive"
        assert result["requires_approval"] is True


def test_unknown_action_classification():
    """Test that unknown actions default to moderate risk."""
    engine = ActionEngine()

    result = engine.classify_action("unknown_action_type")
    assert result["risk_level"] == "moderate"
    assert result["requires_approval"] is False


def test_research_is_safe():
    """Test that research action is classified as safe."""
    engine = ActionEngine()

    result = engine.classify_action("research")
    assert result["risk_level"] == "safe"
    assert result["requires_approval"] is False


def test_analysis_is_safe():
    """Test that analysis action is classified as safe."""
    engine = ActionEngine()

    result = engine.classify_action("analysis")
    assert result["risk_level"] == "safe"
    assert result["requires_approval"] is False


def test_content_draft_is_safe():
    """Test that content_draft action is classified as safe."""
    engine = ActionEngine()

    result = engine.classify_action("content_draft")
    assert result["risk_level"] == "safe"
    assert result["requires_approval"] is False


def test_memory_store_is_safe():
    """Test that memory_store action is classified as safe."""
    engine = ActionEngine()

    result = engine.classify_action("memory_store")
    assert result["risk_level"] == "safe"
    assert result["requires_approval"] is False


def test_log_is_safe():
    """Test that log action is classified as safe."""
    engine = ActionEngine()

    result = engine.classify_action("log")
    assert result["risk_level"] == "safe"
    assert result["requires_approval"] is False


def test_create_account_is_sensitive():
    """Test that create_account action is sensitive."""
    engine = ActionEngine()

    result = engine.classify_action("create_account")
    assert result["risk_level"] == "sensitive"
    assert result["requires_approval"] is True


def test_connect_platform_is_sensitive():
    """Test that connect_platform action is sensitive."""
    engine = ActionEngine()

    result = engine.classify_action("connect_platform")
    assert result["risk_level"] == "sensitive"
    assert result["requires_approval"] is True


def test_publish_content_is_sensitive():
    """Test that publish_content action is sensitive."""
    engine = ActionEngine()

    result = engine.classify_action("publish_content")
    assert result["risk_level"] == "sensitive"
    assert result["requires_approval"] is True


def test_send_message_is_sensitive():
    """Test that send_message action is sensitive."""
    engine = ActionEngine()

    result = engine.classify_action("send_message")
    assert result["risk_level"] == "sensitive"
    assert result["requires_approval"] is True


def test_modify_external_account_is_sensitive():
    """Test that modify_external_account action is sensitive."""
    engine = ActionEngine()

    result = engine.classify_action("modify_external_account")
    assert result["risk_level"] == "sensitive"
    assert result["requires_approval"] is True


def test_create_action_envelope_safe():
    """Test creating action envelope for safe action."""
    engine = ActionEngine()

    payload = {"message": "test"}
    envelope = engine.create_action_envelope("log", payload)

    assert envelope["action_type"] == "log"
    assert envelope["risk_level"] == "safe"
    assert envelope["requires_approval"] is False
    assert envelope["payload"] == payload


def test_create_action_envelope_sensitive():
    """Test creating action envelope for sensitive action."""
    engine = ActionEngine()

    payload = {"content": "test post"}
    envelope = engine.create_action_envelope("publish_content", payload)

    assert envelope["action_type"] == "publish_content"
    assert envelope["risk_level"] == "sensitive"
    assert envelope["requires_approval"] is True
    assert envelope["payload"] == payload


def test_action_envelope_structure():
    """Test that action envelope has correct structure."""
    engine = ActionEngine()

    envelope = engine.create_action_envelope(
        "research",
        {"query": "test query"},
    )

    assert "action_type" in envelope
    assert "risk_level" in envelope
    assert "requires_approval" in envelope
    assert "payload" in envelope
    assert isinstance(envelope["payload"], dict)
