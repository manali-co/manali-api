from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    """Everything comes from app settings / environment. Nothing is read from disk."""

    api_key: str = field(default_factory=lambda: os.environ.get("MANALI_API_KEY", ""))
    site_url: str = field(default_factory=lambda: os.environ.get("MANALI_SITE_URL", "https://manali-co.github.io").rstrip("/"))
    resend_api_key: str = field(default_factory=lambda: os.environ.get("RESEND_API_KEY", ""))
    mail_from: str = field(default_factory=lambda: os.environ.get("MANALI_MAIL_FROM", "manali apps <hello@manali.app>"))
    tables_endpoint: str = field(default_factory=lambda: os.environ.get("MANALI_TABLES_ENDPOINT", ""))
    tables_connection: str = field(default_factory=lambda: os.environ.get("MANALI_TABLES_CONNECTION", ""))
    token_secret: str = field(default_factory=lambda: os.environ.get("MANALI_TOKEN_SECRET", ""))

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.token_secret)


settings = Settings()
