from __future__ import annotations

from typing import Final

from supabase import Client, create_client

from app.config import settings


def is_supabase_configured() -> bool:
    """Return True when the required Supabase environment variables are set."""
    return settings.is_supabase_configured


def get_supabase_client() -> Client | None:
    """Create and return a Supabase client when configuration is available."""
    if not settings.is_supabase_configured:
        return None

    return create_client(settings.supabase_url, settings.supabase_anon_key)


supabase_client: Final[Client | None] = get_supabase_client()
