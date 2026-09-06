"""Configuration module for AEA Core.

Provides settings and configuration access for the application.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Settings:
    """Application settings with sensible defaults."""

    # LLM Configuration
    llm_provider: str = "mock"
    groq_model: str = "llama-3.1-8b-instant"
    groq_api_key: str = ""

    # Database Configuration
    supabase_url: str = ""
    supabase_key: str = ""

    def __post_init__(self):
        """Load settings from environment variables.

        ``SUPABASE_KEY`` is the canonical name; ``SUPABASE_ANON_KEY`` is accepted
        as a backwards-compatible fallback for existing deployments.
        """
        self.llm_provider = os.getenv("LLM_PROVIDER", self.llm_provider)
        self.groq_model = os.getenv("GROQ_MODEL", self.groq_model)
        self.groq_api_key = os.getenv("GROQ_API_KEY", self.groq_api_key)
        self.supabase_url = os.getenv("SUPABASE_URL", self.supabase_url)
        self.supabase_key = (
            os.getenv("SUPABASE_KEY", self.supabase_key)
            or os.getenv("SUPABASE_ANON_KEY", self.supabase_key)
        )


# Global settings instance
settings = Settings()
