"""Platform connector services for Sprint 7.2-B.

This package provides abstractions for integrating AEA with external platforms
through controlled connector abstractions. Connectors support pause/resume workflows
with human intervention checkpoints.
"""

from __future__ import annotations

from .base import ConnectorCapabilities, BaseConnector
from .registry import ConnectorRegistry

__all__ = [
    "BaseConnector",
    "ConnectorCapabilities",
    "ConnectorRegistry",
]
