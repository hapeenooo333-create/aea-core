"""Pinterest connector for Sprint 7.2-B.

This is the MVP Pinterest connector that supports:
- Health checking
- Account status querying
- Onboarding workflow management
- Human intervention checkpoints for OAuth and verification steps

The connector does not automate security-sensitive operations like OTP entry,
CAPTCHA completion, or identity verification. Instead, it creates human
intervention checkpoints and pauses the workflow until the user completes
the required step.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from ..stores.onboarding_workflow_store import OnboardingWorkflowStore
from ..stores.platform_connection_store import PlatformConnectionStore
from .base import BaseConnector, ConnectorCapabilities


class PinterestConnector(BaseConnector):
    """Pinterest platform connector with MVP capabilities.

    This connector manages Pinterest account onboarding workflows with
    human intervention checkpoints for OAuth authorization and verification.

    State is persisted through ``OnboardingWorkflowStore`` and
    ``PlatformConnectionStore``. Both stores fall back to safe in-memory
    storage when Supabase is unavailable. The in-memory dicts on this class
    exist only as the fallback backing store for those services.
    """

    # OAuth / sensitive keys that must never be persisted.
    _FORBIDDEN_AUTH_KEYS = {
        "access_token",
        "refresh_token",
        "authorization_code",
        "oauth_code",
        "client_secret",
        "api_key",
        "token",
        "password",
        "id_token",
        "session",
        "code",
        "redirect_uri",
    }

    def __init__(
        self,
        workflow_store: OnboardingWorkflowStore | None = None,
        connection_store: PlatformConnectionStore | None = None,
    ) -> None:
        """Initialize the Pinterest connector.

        Args:
            workflow_store: Optional pre-constructed
                :class:`OnboardingWorkflowStore`. When ``None``, a default
                store is created (which itself falls back to in-memory
                storage when Supabase is unavailable).
            connection_store: Optional pre-constructed
                :class:`PlatformConnectionStore`.
        """
        super().__init__()
        self._workflow_store = workflow_store or OnboardingWorkflowStore()
        self._connection_store = connection_store or PlatformConnectionStore()
        # These dicts are used only when the stores fall back to their
        # in-memory modes. They remain present so that restart recovery is
        # possible even without Supabase.
        self._account_status_cache: dict[str, dict[str, Any]] = {}
        self._onboarding_workflows: dict[str, dict[str, Any]] = {}

    @property
    def platform(self) -> str:
        """Get the platform name.

        Returns:
            "pinterest"
        """
        return "pinterest"

    @property
    def capabilities(self) -> ConnectorCapabilities:
        """Get Pinterest connector capabilities.

        Returns:
            ConnectorCapabilities describing supported operations.
        """
        return ConnectorCapabilities(
            platform="pinterest",
            health_check=True,
            account_status=True,
            onboarding=True,
            connect_account=True,
            disconnect_account=False,  # Not yet implemented
            publish_content=False,  # Not yet implemented
            get_analytics=False,  # Not yet implemented
            human_intervention_capable=True,
            supported_checkpoint_types=[
                "oauth_authorization_required",
                "email_verification_required",
                "identity_verification_required",
                "manual_platform_step_required",
            ],
        )

    def health_check(self) -> dict[str, Any]:
        """Perform a health check on Pinterest connectivity.

        Returns:
            Dictionary with platform status and details.
        """
        return {
            "success": True,
            "platform": "pinterest",
            "status": "available",
            "details": {
                "api_version": "v5",
                "connector_version": "1.0.0",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }

    def get_account_status(self, worker_id: str | None = None) -> dict[str, Any]:
        """Retrieve the current account status for a worker.

        Prefers the persistent ``PlatformConnectionStore`` so the result
        survives process restart. Falls back to the in-memory cache and
        finally to ``not_started`` when no record exists.

        Args:
            worker_id: Optional worker identifier.

        Returns:
            Dictionary with account state.
        """
        if worker_id:
            persisted = self._connection_store.get(worker_id, "pinterest")
            if persisted:
                status = persisted.get("status") or "not_started"
                return {
                    "success": True,
                    "status": status,
                    "details": {
                        "connected": status == "connected",
                        "requires_action": status in {"onboarding", "needs_reconnect", "failed"},
                        "external_account_id": persisted.get("external_account_id"),
                        "display_name": persisted.get("display_name"),
                        "scopes": persisted.get("scopes") or [],
                    },
                }

            if worker_id in self._account_status_cache:
                return self._account_status_cache[worker_id]

        return {
            "success": True,
            "status": "not_started",
            "details": {
                "connected": False,
                "requires_action": False,
            },
        }

    def start_onboarding(
        self,
        worker_id: str,
        mission_id: str | None = None,
        approval_id: str | None = None,
    ) -> dict[str, Any]:
        """Start a Pinterest onboarding workflow.

        The first step requires OAuth authorization. This method creates
        a human intervention checkpoint for the user to authorize AEA
        to access their Pinterest account.

        Args:
            worker_id: Identifier of the worker initiating onboarding.
            mission_id: Optional identifier of the mission that triggered
                onboarding. Persisted as-is; never invented.
            approval_id: Optional identifier of the approval request that
                authorized this onboarding. When supplied, the connector
                reuses an existing durable workflow bound to this
                approval_id if one exists. This makes ``start_onboarding``
                restart-idempotent across process restarts, HTTP retries,
                and duplicate approval POSTs.

        Returns:
            Dictionary describing workflow state with human checkpoint.
        """
        current_time = datetime.now(timezone.utc).isoformat()

        # If an approval_id is supplied, atomically claim or return the
        # existing durable workflow. The database is the source of truth;
        # this call is safe across process restarts and concurrent resumes.
        if approval_id:
            candidate_workflow_id = str(uuid4())
            checkpoint_data = {
                "checkpoint_type": "oauth_authorization_required",
                "instructions": (
                    "Please authorize AEA to access your Pinterest account. "
                    "Visit the Pinterest authorization page and complete the OAuth flow. "
                    "Once authorized, provide the authorization code back to AEA."
                ),
                "metadata": {
                    "authorization_url": "https://api.pinterest.com/oauth/",
                    "scopes": [
                        "user_accounts:read",
                        "boards:read",
                        "pins:create",
                    ],
                },
            }
            step_history = [
                {
                    "step": 1,
                    "name": "OAuth Authorization",
                    "status": "pending",
                    "description": "Authorize AEA to access Pinterest account",
                    "checkpoint_type": "oauth_authorization_required",
                    "completed_at": None,
                }
            ]
            claim = self._workflow_store.get_or_create_for_approval(
                approval_id=approval_id,
                workflow_id=candidate_workflow_id,
                mission_id=mission_id,
                worker_id=worker_id,
                platform="pinterest",
                status="awaiting_human",
                current_step=1,
                total_steps=3,
                checkpoint_data=checkpoint_data,
                step_history=step_history,
            )
            if claim.get("success"):
                existing = claim["workflow"]
                return {
                    "success": True,
                    "status": existing.get("status") or "awaiting_human",
                    "workflow_id": existing.get("workflow_id"),
                    "platform": "pinterest",
                    "current_step": existing.get("current_step") or 1,
                    "total_steps": existing.get("total_steps") or 3,
                    "next_step": "oauth_authorization_required",
                    "requires_human_intervention": True,
                    "checkpoint_type": "oauth_authorization_required",
                    "instructions": checkpoint_data["instructions"],
                    "metadata": checkpoint_data["metadata"],
                    "started_by_approval_id": existing.get("started_by_approval_id"),
                    "reused_existing_workflow": claim.get("created") is False,
                }
            # If the claim call failed, fall through to the legacy path.

        # Legacy / no-approval path: always create a fresh workflow.
        workflow_id = str(uuid4())

        # Create the initial workflow state
        checkpoint_data = {
            "checkpoint_type": "oauth_authorization_required",
            "instructions": (
                "Please authorize AEA to access your Pinterest account. "
                "Visit the Pinterest authorization page and complete the OAuth flow. "
                "Once authorized, provide the authorization code back to AEA."
            ),
            "metadata": {
                "authorization_url": "https://api.pinterest.com/oauth/",
                "scopes": [
                    "user_accounts:read",
                    "boards:read",
                    "pins:create",
                ],
            },
        }
        step_history = [
            {
                "step": 1,
                "name": "OAuth Authorization",
                "status": "pending",
                "description": "Authorize AEA to access Pinterest account",
                "checkpoint_type": "oauth_authorization_required",
                "completed_at": None,
            }
        ]

        workflow_state = {
            "workflow_id": workflow_id,
            "mission_id": mission_id,
            "worker_id": worker_id,
            "platform": "pinterest",
            "status": "awaiting_human",
            "current_step": 1,
            "total_steps": 3,
            "checkpoint_type": "oauth_authorization_required",
            "created_at": current_time,
            "updated_at": current_time,
            "step_history": list(step_history),
            "checkpoint_data": dict(checkpoint_data),
        }

        # Persist via the store. The store itself manages DB-first writes
        # and in-memory fallback, so this call is safe in all environments.
        result = self._workflow_store.create(
            workflow_id=workflow_id,
            mission_id=mission_id,
            worker_id=worker_id,
            platform="pinterest",
            status="awaiting_human",
            current_step=1,
            total_steps=3,
            checkpoint_data=checkpoint_data,
            step_history=step_history,
        )
        if not result.get("success"):
            # Should not normally happen; fall back to local cache.
            self._onboarding_workflows[workflow_id] = workflow_state

        return {
            "success": True,
            "status": "awaiting_human",
            "workflow_id": workflow_id,
            "platform": "pinterest",
            "current_step": 1,
            "total_steps": 3,
            "next_step": "oauth_authorization_required",
            "requires_human_intervention": True,
            "checkpoint_type": "oauth_authorization_required",
            "instructions": checkpoint_data["instructions"],
            "metadata": checkpoint_data["metadata"],
        }

    def resume_onboarding(self, workflow_id: str, human_input: dict[str, Any]) -> dict[str, Any]:
        """Resume an onboarding workflow after human completion of a checkpoint.

        This method processes the human's completion of a checkpoint (e.g., OAuth
        authorization) and moves to the next step in the workflow.

        Workflow state is fetched through the persistent store (DB-first) so
        that resume works after process restart without requiring the workflow
        to be present in the connector's local cache.

        Args:
            workflow_id: Identifier of the workflow to resume.
            human_input: Data provided by human completing the checkpoint.
                        For OAuth, this includes the authorization code.

        Returns:
            Dictionary describing resumed workflow state.
        """
        # Sanitize incoming human input before persisting any of it.
        safe_human_input = self._sanitize_human_input(human_input)

        workflow = self._workflow_store.get(workflow_id)
        if workflow is None:
            return {
                "success": False,
                "error": f"Workflow {workflow_id} not found",
                "workflow_id": workflow_id,
            }

        current_time = datetime.now(timezone.utc).isoformat()

        # Mark current step as completed
        step_history = list(workflow.get("step_history") or [])
        if step_history:
            step_history[-1] = dict(step_history[-1])
            step_history[-1]["status"] = "completed"
            step_history[-1]["completed_at"] = current_time

        # Move to next step
        current_step = int(workflow.get("current_step") or 1)
        total_steps = int(workflow.get("total_steps") or 3)
        next_step = current_step + 1

        if next_step > total_steps:
            # Onboarding complete
            checkpoint_data = dict(workflow.get("checkpoint_data") or {})
            update_result = self._workflow_store.update(
                workflow_id,
                status="completed",
                current_step=total_steps,
                checkpoint_data=checkpoint_data,
                step_history=step_history,
            )
            if not update_result.get("success"):
                # Maintain local cache as last resort.
                self._onboarding_workflows[workflow_id] = dict(workflow)

            # Mark the platform connection as connected for the worker.
            worker_id = workflow.get("worker_id")
            if worker_id:
                self._connection_store.upsert(
                    owner_id=worker_id,
                    platform="pinterest",
                    status="connected",
                )

            return {
                "success": True,
                "status": "completed",
                "workflow_id": workflow_id,
                "platform": "pinterest",
                "current_step": total_steps,
                "total_steps": total_steps,
                "requires_human_intervention": False,
                "instructions": "Onboarding completed successfully!",
            }

        if next_step == 2:
            # Step 2: Email verification
            checkpoint_data = {
                "checkpoint_type": "email_verification_required",
                "instructions": (
                    "Pinterest requires email verification. Check your email for "
                    "a verification link and complete the verification. Once verified, "
                    "provide confirmation back to AEA."
                ),
                "metadata": {
                    "verification_sent_to": safe_human_input.get("email", "***"),
                },
            }
            step_history.append({
                "step": 2,
                "name": "Email Verification",
                "status": "pending",
                "description": "Verify your Pinterest account email address",
                "checkpoint_type": "email_verification_required",
                "completed_at": None,
            })
            update_result = self._workflow_store.update(
                workflow_id,
                status="awaiting_human",
                current_step=2,
                checkpoint_data=checkpoint_data,
                step_history=step_history,
            )
            if not update_result.get("success"):
                self._onboarding_workflows[workflow_id] = dict(workflow)

            return {
                "success": True,
                "status": "awaiting_human",
                "workflow_id": workflow_id,
                "platform": "pinterest",
                "current_step": 2,
                "total_steps": 3,
                "next_step": "email_verification_required",
                "requires_human_intervention": True,
                "checkpoint_type": "email_verification_required",
                "instructions": checkpoint_data["instructions"],
                "metadata": checkpoint_data["metadata"],
            }

        if next_step == 3:
            # Step 3: Account configuration
            checkpoint_data = {
                "checkpoint_type": "manual_platform_step_required",
                "instructions": (
                    "Finally, verify your account is configured for affiliate content. "
                    "Log into Pinterest and confirm your account settings allow "
                    "affiliate links and branded content. Once verified, provide confirmation."
                ),
                "metadata": {
                    "settings_checklist": [
                        "Account type is 'Creator' or 'Business'",
                        "Affiliate disclosure is enabled",
                        "Brand partnerships are allowed",
                    ],
                },
            }
            step_history.append({
                "step": 3,
                "name": "Account Configuration",
                "status": "pending",
                "description": "Configure your Pinterest account settings for affiliate use",
                "checkpoint_type": "manual_platform_step_required",
                "completed_at": None,
            })
            update_result = self._workflow_store.update(
                workflow_id,
                status="awaiting_human",
                current_step=3,
                checkpoint_data=checkpoint_data,
                step_history=step_history,
            )
            if not update_result.get("success"):
                self._onboarding_workflows[workflow_id] = dict(workflow)

            return {
                "success": True,
                "status": "awaiting_human",
                "workflow_id": workflow_id,
                "platform": "pinterest",
                "current_step": 3,
                "total_steps": 3,
                "next_step": "manual_platform_step_required",
                "requires_human_intervention": True,
                "checkpoint_type": "manual_platform_step_required",
                "instructions": checkpoint_data["instructions"],
                "metadata": checkpoint_data["metadata"],
            }

        # Unexpected state
        return {
            "success": False,
            "error": f"Unexpected workflow state at step {next_step}",
            "workflow_id": workflow_id,
        }

    def connect_account(self, worker_id: str, auth_data: dict[str, Any]) -> dict[str, Any]:
        """Establish a connection to a Pinterest account.

        Only safe metadata is persisted. OAuth secrets, authorization codes,
        and similar credentials are stripped before being passed to the store.

        Args:
            worker_id: Identifier of the worker.
            auth_data: Authorization data (must include oauth_code or similar).

        Returns:
            Dictionary with connection result.
        """
        if not auth_data or "oauth_code" not in auth_data:
            return {
                "success": False,
                "error": "OAuth authorization code required in auth_data",
            }

        safe_metadata = self._sanitize_human_input(auth_data)
        external_account_id = safe_metadata.get("external_account_id")
        display_name = safe_metadata.get("display_name")
        scopes = safe_metadata.get("scopes")

        self._connection_store.upsert(
            owner_id=worker_id,
            platform="pinterest",
            status="connected",
            external_account_id=external_account_id,
            display_name=display_name,
            scopes=scopes,
        )

        return {
            "success": True,
            "status": "connected",
            "worker_id": worker_id,
            "platform": "pinterest",
            "message": "Successfully connected to Pinterest account",
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @classmethod
    def _sanitize_human_input(cls, human_input: Any) -> dict[str, Any]:
        """Strip OAuth secrets from arbitrary human input before persistence."""
        if not isinstance(human_input, dict):
            return {}

        def _clean(value: Any) -> Any:
            if isinstance(value, dict):
                return {k: _clean(v) for k, v in value.items() if k.lower() not in cls._FORBIDDEN_AUTH_KEYS}
            if isinstance(value, list):
                return [_clean(v) for v in value]
            return value

        return _clean(human_input)
