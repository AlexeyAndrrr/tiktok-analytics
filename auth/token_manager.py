import json
import time
import base64
import hashlib
from pathlib import Path

import httpx
from cryptography.fernet import Fernet

from config import settings


class TokenManager:
    """Manages TikTok OAuth2 tokens per account."""

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
        """List all account IDs that have stored tokens."""
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
        # Fallback: first available account
        ids = self.list_account_ids()
        return ids[0] if ids else None

    def set_primary(self, account_id: int):
        """Set the primary account."""
        meta = {}
        if self._metadata_path.exists():
            meta = json.loads(self._metadata_path.read_text())
        meta["primary_account_id"] = account_id
        self._metadata_path.write_text(json.dumps(meta))

        # Update DB
        from db.models import Account
        Account.update(is_primary=False).execute()
        Account.update(is_primary=True).where(Account.id == account_id).execute()

    # ── Token exchange ─────────────────────────────────

    def exchange_code(self, auth_code: str, code_verifier: str) -> dict:
        """Exchange authorization code for tokens. Creates Account in DB."""
        resp = httpx.post(
            f"{settings.TIKTOK_API_BASE}/oauth/token/",
            data={
                "client_key": settings.TIKTOK_CLIENT_KEY,
                "client_secret": settings.TIKTOK_CLIENT_SECRET,
                "code": auth_code,
                "grant_type": "authorization_code",
                "redirect_uri": settings.OAUTH_REDIRECT_URI,
                "code_verifier": code_verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        data = resp.json()

        if "access_token" not in data:
            raise ValueError(f"Token exchange failed: {data}")

        open_id = data["open_id"]

        # Create or get Account in DB
        from db.database import init_db
        from db.models import Account
        init_db()

        is_first = Account.select().count() == 0
        account, created = Account.get_or_create(
            open_id=open_id,
            defaults={"is_primary": is_first},
        )

        if is_first:
            self.set_primary(account.id)

        token_data = {
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
            "open_id": open_id,
            "account_id": account.id,
            "scope": data.get("scope", ""),
            "expires_at": time.time() + data.get("expires_in", 86400),
            "refresh_expires_at": time.time() + data.get("refresh_expires_in", 31536000),
        }
        self._save(token_data, account.id)
        self._account_id = account.id
        return token_data

    # ── Token storage ──────────────────────────────────

    def _save(self, token_data: dict, account_id: int | None = None):
        aid = account_id or self.account_id
        if aid is None:
            raise RuntimeError("No account ID for saving tokens")
        raw = json.dumps(token_data).encode()
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

    # ── Token operations ───────────────────────────────

    def is_access_valid(self, account_id: int | None = None) -> bool:
        tokens = self.load(account_id)
        if not tokens:
            return False
        return time.time() < tokens["expires_at"] - 60

    def get_access_token(self, account_id: int | None = None) -> str:
        aid = account_id or self.account_id
        if not self.is_access_valid(aid):
            self.refresh(aid)
        tokens = self.load(aid)
        if not tokens:
            raise RuntimeError("Not authenticated")
        return tokens["access_token"]

    def get_open_id(self, account_id: int | None = None) -> str:
        tokens = self.load(account_id)
        if not tokens:
            raise RuntimeError("Not authenticated")
        return tokens["open_id"]

    def refresh(self, account_id: int | None = None) -> dict:
        aid = account_id or self.account_id
        tokens = self.load(aid)
        if not tokens:
            raise RuntimeError("No tokens to refresh")

        resp = httpx.post(
            f"{settings.TIKTOK_API_BASE}/oauth/token/",
            data={
                "client_key": settings.TIKTOK_CLIENT_KEY,
                "client_secret": settings.TIKTOK_CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        data = resp.json()

        if "access_token" not in data:
            raise ValueError(f"Token refresh failed: {data}")

        tokens["access_token"] = data["access_token"]
        tokens["refresh_token"] = data["refresh_token"]
        tokens["expires_at"] = time.time() + data.get("expires_in", 86400)
        tokens["refresh_expires_at"] = time.time() + data.get("refresh_expires_in", 31536000)
        self._save(tokens, aid)
        return tokens

    def revoke(self, account_id: int | None = None):
        aid = account_id or self.account_id
        tokens = self.load(aid)
        if tokens:
            try:
                httpx.post(
                    f"{settings.TIKTOK_API_BASE}/oauth/revoke/",
                    data={
                        "client_key": settings.TIKTOK_CLIENT_KEY,
                        "token": tokens["access_token"],
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            except Exception:
                pass
        if aid:
            path = self._token_path(aid)
            if path.exists():
                path.unlink()

            # Remove account from DB
            from db.models import Account
            Account.delete().where(Account.id == aid).execute()

            # If was primary, reassign
            if self.get_primary_id() == aid or self.get_primary_id() is None:
                remaining = self.list_account_ids()
                if remaining:
                    self.set_primary(remaining[0])

    def status(self, account_id: int | None = None) -> dict | None:
        tokens = self.load(account_id)
        if not tokens:
            return None
        return {
            "account_id": tokens.get("account_id"),
            "open_id": tokens["open_id"],
            "scope": tokens.get("scope", ""),
            "access_valid": time.time() < tokens["expires_at"],
            "access_expires_in": max(0, int(tokens["expires_at"] - time.time())),
            "refresh_expires_in": max(0, int(tokens["refresh_expires_at"] - time.time())),
        }
