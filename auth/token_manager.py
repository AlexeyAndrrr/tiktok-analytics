"""Manages TikTok session cookies per account (encrypted storage)."""

import json
import time
import base64
import hashlib
import logging
from pathlib import Path

import httpx
from cryptography.fernet import Fernet

from config import settings

logger = logging.getLogger(__name__)


class TokenManager:
    """Manages TikTok browser session cookies per account."""

    def __init__(self, account_id: int | None = None):
        self._fernet = self._create_fernet(settings.TOKEN_ENCRYPTION_KEY)
        self._account_id = account_id
        self._metadata_path = settings.TOKENS_DIR / "_metadata.json"

    @property
    def account_id(self) -> int | None:
        if self._account_id is not None:
            return self._account_id
        return self.get_primary_id()

    def _token_path(self, account_id: int) -> Path:
        return settings.TOKENS_DIR / f"{account_id}.json"

    @staticmethod
    def _create_fernet(passphrase: str) -> Fernet:
        key = hashlib.sha256(passphrase.encode()).digest()
        return Fernet(base64.urlsafe_b64encode(key))

    # ── Account management ─────────────────────────────

    def list_account_ids(self) -> list[int]:
        """List all account IDs that have stored sessions."""
        ids = []
        for f in settings.TOKENS_DIR.glob("*.json"):
            if f.stem.startswith("_"):
                continue
            try:
                ids.append(int(f.stem))
            except ValueError:
                continue
        return sorted(ids)

    def get_primary_id(self) -> int | None:
        """Get the primary account ID."""
        if self._metadata_path.exists():
            meta = json.loads(self._metadata_path.read_text())
            return meta.get("primary_account_id")
        ids = self.list_account_ids()
        return ids[0] if ids else None

    def set_primary(self, account_id: int):
        """Set the primary account."""
        meta = {}
        if self._metadata_path.exists():
            meta = json.loads(self._metadata_path.read_text())
        meta["primary_account_id"] = account_id
        self._metadata_path.write_text(json.dumps(meta))

        from db.models import Account
        Account.update(is_primary=False).execute()
        Account.update(is_primary=True).where(Account.id == account_id).execute()

    # ── Session storage ────────────────────────────────

    def store_session(self, login_id: str, cookies: dict, username: str = "") -> dict:
        """
        Store browser session cookies for an account.
        Creates Account in DB if needed.
        Returns session_data dict with account_id.
        """
        from db.database import init_db
        from db.models import Account
        init_db()

        is_first = Account.select().count() == 0

        # Extract user ID from cookies if available
        open_id = cookies.get("uid_tt", "")

        account, created = Account.get_or_create(
            login_id=login_id,
            defaults={
                "open_id": open_id,
                "display_name": username or login_id,
                "username": username or None,
                "is_primary": is_first,
            },
        )

        if is_first:
            self.set_primary(account.id)

        session_data = {
            "cookies": cookies,
            "login_id": login_id,
            "username": username or login_id,
            "account_id": account.id,
            "open_id": open_id,
            "stored_at": time.time(),
        }
        self._save(session_data, account.id)
        self._account_id = account.id
        return session_data

    def _save(self, data: dict, account_id: int | None = None):
        aid = account_id or self.account_id
        if aid is None:
            raise RuntimeError("No account ID for saving session")
        raw = json.dumps(data).encode()
        encrypted = self._fernet.encrypt(raw)
        self._token_path(aid).write_bytes(encrypted)

    def load(self, account_id: int | None = None) -> dict | None:
        aid = account_id or self.account_id
        if aid is None:
            return None
        path = self._token_path(aid)
        if not path.exists():
            return None
        encrypted = path.read_bytes()
        raw = self._fernet.decrypt(encrypted)
        return json.loads(raw)

    def has_any_accounts(self) -> bool:
        return len(self.list_account_ids()) > 0

    # ── Cookie operations ──────────────────────────────

    def get_cookies(self, account_id: int | None = None) -> dict:
        """Get session cookies dict for an account."""
        data = self.load(account_id)
        if not data or "cookies" not in data:
            raise RuntimeError("Not authenticated — no session cookies.")
        return data["cookies"]

    def is_session_valid(self, account_id: int | None = None) -> bool:
        """Check if stored session cookies are still valid."""
        data = self.load(account_id)
        if not data or "cookies" not in data:
            return False

        # Quick check: if stored within last hour, assume valid
        stored_at = data.get("stored_at", 0)
        if time.time() - stored_at < 3600:
            return True

        # Test request to verify cookies
        try:
            username = data.get("username", "")
            if not username:
                return True  # Can't verify without username, assume valid

            resp = httpx.get(
                "https://www.tiktok.com/api/user/detail/",
                params={"uniqueId": username},
                cookies=data["cookies"],
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Referer": "https://www.tiktok.com/",
                },
                timeout=10,
                follow_redirects=True,
            )
            return resp.status_code == 200 and "userInfo" in resp.text
        except Exception as e:
            logger.warning(f"Session validation failed: {e}")
            return False

    def revoke(self, account_id: int | None = None):
        """Remove session and account."""
        aid = account_id or self.account_id

        if aid:
            path = self._token_path(aid)
            if path.exists():
                path.unlink()

            from db.models import Account
            Account.delete().where(Account.id == aid).execute()

            # Reassign primary if needed
            if self.get_primary_id() == aid or self.get_primary_id() is None:
                remaining = self.list_account_ids()
                if remaining:
                    self.set_primary(remaining[0])

    def status(self, account_id: int | None = None) -> dict | None:
        """Get session status info."""
        data = self.load(account_id)
        if not data:
            return None
        stored_at = data.get("stored_at", 0)
        age_hours = (time.time() - stored_at) / 3600 if stored_at else 0
        return {
            "account_id": data.get("account_id"),
            "login_id": data.get("login_id", ""),
            "username": data.get("username", ""),
            "session_valid": self.is_session_valid(account_id),
            "stored_hours_ago": round(age_hours, 1),
            "cookies_count": len(data.get("cookies", {})),
        }
