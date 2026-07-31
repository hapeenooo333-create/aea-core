"""Supabase database client helpers for the AEA Core FastAPI backend."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Final

from supabase import Client, create_client

from .config import settings

logger: Final[logging.Logger] = logging.getLogger(__name__)


class DatabaseError(RuntimeError):
    """Raised when the Supabase client cannot be initialized."""


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    """Create and cache the singleton Supabase client instance."""

    url: str = settings.supabase_url
    key: str = settings.supabase_anon_key

    if not url or not key:
        raise RuntimeError(
            "Supabase initialization failed: SUPABASE_URL and SUPABASE_ANON_KEY must be configured."
        )

    try:
        client: Client = create_client(url, key)
    except Exception as exc:  # pragma: no cover - defensive initialization path
        raise RuntimeError(f"Supabase initialization failed: {exc}") from exc

    logger.info("Supabase client initialized successfully.")
    return client


supabase_client: Final[Client] = get_supabase_client()

__all__ = ["DatabaseError", "get_supabase_client", "supabase_client"]

                                                                                                                                                                                    