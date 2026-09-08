"""Lightweight tool registry service for Sprint 4.2.

This module maintains an in-memory registry of agent tools that can be used by
future runtime workflows. The implementation stays deliberately small and
safe so it can be imported in tests and local development environments without
requiring database or external service dependencies.
"""

from __future__ import annotations

from typing import Any

from .p1_7_contracts import ToolContract


class ToolRegistry:
    """Maintain a lightweight registry of available agent tools.

    The registry is intentionally in-memory for now, but the structure is kept
    simple enough to support future persistence without larger refactoring.
    """

    def __init__(self) -> None:
        """Initialize an empty tool registry."""

        self._tools: dict[str, dict[str, Any]] = {}

    def register_tool(
        self,
        name: str,
        description: str,
        tool_type: str = "internal",
        schema: dict[str, Any] | None = None,
        *,
        version: str = "1.0",
        output_schema: dict[str, Any] | None = None,
        capability: str | None = None,
        platform: str | None = None,
        operation: str | None = None,
        risk_level: str | None = None,
        requires_connection: bool = False,
        requires_approval: bool | None = None,
        supports_dry_run: bool = True,
        idempotency_behavior: str = "not_applicable",
        timeout: float = 30.0,
        retry_policy: str = "bounded",
        required_scopes: list[str] | None = None,
    ) -> dict[str, Any]:
        """Register a new tool definition.

        Args:
            name: The unique tool identifier.
            description: A brief explanation of the tool's purpose.
            tool_type: The tool category, such as ``internal`` or ``external``.
            schema: Optional JSON schema for payload validation.

        Returns:
            A structured dictionary describing the registration outcome.
        """

        normalized_name = (name or "").strip()
        if not normalized_name:
            return {"success": False, "error": "Tool name is required"}

        canonical_risk = risk_level or ("WRITE_EXTERNAL" if tool_type == "external" else "READ_ONLY")
        canonical_approval = requires_approval if requires_approval is not None else canonical_risk in {"WRITE_EXTERNAL", "DESTRUCTIVE"}
        tool_payload = ToolContract(
            tool_name=normalized_name,
            version=version,
            description=description or "",
            input_schema=schema or {},
            output_schema=output_schema or {},
            capability=capability,
            platform=platform,
            operation=operation,
            risk_level=canonical_risk,
            requires_connection=requires_connection,
            requires_approval=canonical_approval,
            supports_dry_run=supports_dry_run,
            idempotency_behavior=idempotency_behavior,
            timeout=timeout,
            retry_policy=retry_policy,
        ).to_dict()
        tool_payload["required_scopes"] = list(required_scopes or [])
        self._tools[normalized_name] = tool_payload
        return {"success": True, "tool": tool_payload}

    def register_contract(
        self,
        contract: ToolContract,
        *,
        required_scopes: list[str] | None = None,
    ) -> dict[str, Any]:
        """Register a canonical contract without exposing mutable registry state."""
        return self.register_tool(
            contract.tool_name,
            contract.description,
            schema=contract.input_schema,
            version=contract.version,
            output_schema=contract.output_schema,
            capability=contract.capability,
            platform=contract.platform,
            operation=contract.operation,
            risk_level=contract.risk_level,
            requires_connection=contract.requires_connection,
            requires_approval=contract.requires_approval,
            supports_dry_run=contract.supports_dry_run,
            idempotency_behavior=contract.idempotency_behavior,
            timeout=contract.timeout,
            retry_policy=contract.retry_policy,
            required_scopes=required_scopes,
        )

    def get_tool(self, name: str) -> dict[str, Any]:
        """Retrieve a specific tool definition.

        Args:
            name: The tool identifier to retrieve.

        Returns:
            A structured dictionary containing the tool when it exists, or an
            error payload when it does not.
        """

        normalized_name = (name or "").strip()
        if not normalized_name:
            return {"success": False, "error": "Tool name is required"}

        tool = self._tools.get(normalized_name)
        if not tool:
            return {"success": False, "error": f"Tool not found: {normalized_name}"}

        return {"success": True, "tool": tool}

    def list_tools(self) -> dict[str, Any]:
        """Return all registered tools.

        Returns:
            A structured dictionary containing the current registry contents.
        """

        tools = [dict(tool) for tool in self._tools.values()]
        return {"success": True, "tools": tools}

    def is_available(self, name: str) -> dict[str, Any]:
        """Check whether a tool exists in the registry.

        Args:
            name: The tool identifier to inspect.

        Returns:
            A structured dictionary with the availability result.
        """

        normalized_name = (name or "").strip()
        if not normalized_name:
            return {"success": True, "available": False, "error": "Tool name is required"}

        return {"success": True, "available": normalized_name in self._tools}

    def remove_tool(self, name: str) -> dict[str, Any]:
        """Remove a registered tool if it exists.

        Args:
            name: The tool identifier to remove.

        Returns:
            A structured dictionary describing whether the removal succeeded.
        """

        normalized_name = (name or "").strip()
        if not normalized_name:
            return {"success": False, "error": "Tool name is required"}

        if normalized_name not in self._tools:
            return {"success": True, "removed": False, "name": normalized_name}

        del self._tools[normalized_name]
        return {"success": True, "removed": True, "name": normalized_name}


__all__ = ["ToolRegistry"]
