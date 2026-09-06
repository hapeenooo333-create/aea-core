from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.decision_engine import AtlasDecisionEngine


class FakeMemoryEngine:
    def __init__(self, memories=None):
        self.memories = memories or []
        self.stored: list[dict] = []

    def get_recent_memories(self, worker_id: str, limit: int = 5):
        return list(self.memories)

    def store_memory(self, worker_id: str, memory_type: str, content: dict, owner_id: str | None = None):
        self.stored.append({"worker_id": worker_id, "memory_type": memory_type, "content": content, "owner_id": owner_id})
        return {"success": True}


class StubProvider:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error

    def generate(self, prompt: str, system_prompt: str | None = None):
        if self.error:
            raise self.error
        return self.response or {"success": True, "content": "Use the next available worker", "provider": "stub"}


class FailingProvider:
    def generate(self, prompt: str, system_prompt: str | None = None):
        raise RuntimeError("provider unavailable")


def test_decision_with_no_memories_builds_empty_context():
    memory_engine = FakeMemoryEngine([])
    engine = AtlasDecisionEngine(provider=StubProvider(), memory_engine=memory_engine)

    decision = engine.next_action_details(worker_id="worker-1", mission={"title": "Publish content"})

    assert decision["success"] is True
    assert decision["context"]["worker_id"] == "worker-1"
    assert decision["context"]["recent_memories"] == []
    assert decision["context"]["mission"]["title"] == "Publish content"


def test_decision_with_recent_memories_includes_memory_context():
    memory_engine = FakeMemoryEngine([
        {"id": "m-1", "memory_type": "summary", "content": {"text": "prioritize content"}}
    ])
    engine = AtlasDecisionEngine(provider=StubProvider(), memory_engine=memory_engine)

    decision = engine.next_action_details(worker_id="worker-2", mission={"title": "Research topic"})

    assert decision["context"]["recent_memories"][0]["content"]["text"] == "prioritize content"
    assert decision["context"]["mission"]["title"] == "Research topic"


def test_fallback_provider_behavior_is_preserved():
    engine = AtlasDecisionEngine(provider=FailingProvider(), memory_engine=FakeMemoryEngine([]))

    decision = engine.next_action_details(worker_id="worker-3", mission={"title": "Fallback mission"})

    assert decision["success"] is True
    assert decision["action"].startswith("Mock response")


def test_memory_saved_after_successful_decision():
    memory_engine = FakeMemoryEngine([])
    engine = AtlasDecisionEngine(provider=StubProvider(response={"success": True, "action": "Escalate"}), memory_engine=memory_engine)

    engine.next_action_details(worker_id="worker-4", mission={"title": "Escalation task"})

    assert len(memory_engine.stored) == 1
    assert memory_engine.stored[0]["memory_type"] == "decision"
    assert memory_engine.stored[0]["content"]["action"] == "Escalate"


def test_next_action_remains_backward_compatible():
    engine = AtlasDecisionEngine(provider=StubProvider(response={"success": True, "content": "Proceed"}), memory_engine=FakeMemoryEngine([]))

    action = engine.next_action()

    assert isinstance(action, str)
    assert action
