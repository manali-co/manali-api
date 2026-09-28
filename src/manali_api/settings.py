from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str = "") -> str:
    """Set-but-empty counts as unset (the deploy passes every variable, filled or not)."""
    return os.environ.get(name, "").strip() or default


@dataclass(frozen=True)
class Settings:
    """Everything comes from app settings / environment. Nothing is read from disk."""

    # "prod" unless told otherwise; only "local" and "test" may fake email and storage.
    env: str = field(default_factory=lambda: _env("MANALI_ENV", "prod"))
    api_key: str = field(default_factory=lambda: _env("MANALI_API_KEY"))
    # Separate key for /admin/*: the site's public routes never need it, so a leak of the
    # site key does not hand over the subscriber list or the announce button.
    admin_key: str = field(default_factory=lambda: _env("MANALI_ADMIN_KEY"))
    site_url: str = field(default_factory=lambda: _env("MANALI_SITE_URL").rstrip("/"))
    resend_api_key: str = field(default_factory=lambda: _env("RESEND_API_KEY"))
    mail_from: str = field(default_factory=lambda: _env("MANALI_MAIL_FROM", "manali apps <hello@manali.page>"))
    tables_endpoint: str = field(default_factory=lambda: _env("MANALI_TABLES_ENDPOINT"))
    tables_connection: str = field(default_factory=lambda: _env("MANALI_TABLES_CONNECTION"))
    token_secret: str = field(default_factory=lambda: _env("MANALI_TOKEN_SECRET"))
    # Optional postal line for the email footer (some jurisdictions expect one for list mail).
    mail_address: str = field(default_factory=lambda: _env("MANALI_MAIL_ADDRESS"))

    @property
    def fake_allowed(self) -> bool:
        return self.env in ("local", "test")

    @property
    def site_ok(self) -> bool:
        return self.site_url.startswith("https://") or (self.fake_allowed and self.site_url.startswith("http"))

    @property
    def problems(self) -> list[str]:
        """Why the API should refuse to serve. Empty means ready."""
        out = []
        if len(self.api_key) < 32:
            out.append("MANALI_API_KEY missing or shorter than 32 characters")
        if len(self.token_secret) < 32:
            out.append("MANALI_TOKEN_SECRET missing or shorter than 32 characters")
        if not self.site_ok:
            out.append("MANALI_SITE_URL must be an https URL")
        if not self.fake_allowed and not (self.tables_endpoint or self.tables_connection):
            out.append("MANALI_TABLES_ENDPOINT missing")
        return out

    @property
    def configured(self) -> bool:
        return not self.problems

    @property
    def mail_ready(self) -> bool:
        return bool(self.resend_api_key)


settings = Settings()
