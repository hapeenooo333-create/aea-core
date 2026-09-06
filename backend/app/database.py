"""Database module for AEA Core.

Provides database client initialization and connection management.
"""

from __future__ import annotations

import os
from typing import Any

# Placeholder for Supabase client
supabase_client: Any = None


def _resolve_supabase_credential() -> tuple[str, str]:
    """Resolve Supabase URL and key from supported environment variable names.

    ``SUPABASE_KEY`` takes precedence. ``SUPABASE_ANON_KEY`` is accepted as a
    backwards-compatible fallback for deployments that already configure it.
    """

    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_KEY", "") or os.getenv("SUPABASE_ANON_KEY", "")
    return url, key


def is_supabase_configured() -> bool:
    """Check if Supabase is configured.

    Returns:
        True if Supabase credentials are available, False otherwise.
    """
    url, key = _resolve_supabase_credential()
    return bool(url and key)


def get_supabase_client() -> Any:
    """Get or initialize the Supabase client.

    Returns:
        The Supabase client instance, or None if not configured.
    """
    global supabase_client

    if supabase_client is not None:
        return supabase_client

    # Attempt to initialize if configured
    url, key = _resolve_supabase_credential()

    if not (url and key):
        return None

    try:
        from supabase import create_client

        supabase_client = create_client(url, key)
        return supabase_client
    except Exception:  # pragma: no cover - defensive runtime handling
        return None


# Initialize on import if configured
if is_supabase_configured():
    supabase_client = get_supabase_client()
