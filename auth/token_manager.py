import json
import time
import base64
import hashlib

import httpx
from cryptography.fernet import Fernet

from config import settings


class TokenManager:
    """Manages TikTok OAuth2 tokens: exchange, storage, refresh, revocation."""

    def __init__(self):
        self.token_path = settings.TOKEN_PATH
        self._fernet = self._create_fernet(settings.TOKEN_ENCRYPTION_KEY)

    @staticmethod
    def _create_fernet(passphrase: str) -> Fernet:
        key = hashlib.sha256(passphrase.encode()).digest()
        return Fernet(base64.urlsafe_b64encode(key))

    def exchange_code(self, auth_code: str, code_verifier: str) -> dict:
        """Exchange authorization code for access and refresh tokens."""
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

        token_data = {
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
            "open_id": data["open_id"],
            "scope": data.get("scope", ""),
            "expires_at": time.time() + data.get("expires_in", 86400),
            "refresh_expires_at": time.time() + data.get("refresh_expires_in", 31536000),
        }
        self._save(token_data)
        return token_data

    def _save(self, token_data: dict):
        """Encrypt and save tokens to disk."""
        raw = json.dumps(token_data).encode()
        encrypted = self._fernet.encrypt(raw)
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_bytes(encrypted)

    def load(self) -> dict | None:
        """Load and decrypt tokens. Returns None if not found."""
        if not self.token_path.exists():
            return None
        encrypted = self.token_path.read_bytes()
        raw = self._fernet.decrypt(encrypted)
        return json.loads(raw)

    def is_access_valid(self) -> bool:
        tokens = self.load()
        if not tokens:
            return False
        return time.time() < tokens["expires_at"] - 60  # 1 min buffer

    def get_access_token(self) -> str:
        """Return a valid access token, refreshing if needed."""
        if not self.is_access_valid():
            self.refresh()
        tokens = self.load()
        if not tokens:
            raise RuntimeError("Not authenticated. Run: tiktok-analytics auth login")
        return tokens["access_token"]

    def get_open_id(self) -> str:
        tokens = self.load()
        if not tokens:
            raise RuntimeError("Not authenticated. Run: tiktok-analytics auth login")
        return tokens["open_id"]

    def refresh(self) -> dict:
        """Refresh the access token using the refresh token."""
        tokens = self.load()
        if not tokens:
            raise RuntimeError("No tokens to refresh. Run: tiktok-analytics auth login")

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
        self._save(tokens)
        return tokens

    def revoke(self):
        """Revoke tokens and delete local storage."""
        tokens = self.load()
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
                pass  # Best effort revocation
        if self.token_path.exists():
            self.token_path.unlink()

    def status(self) -> dict | None:
        """Return token status info for display."""
        tokens = self.load()
        if not tokens:
            return None
        return {
            "open_id": tokens["open_id"],
            "scope": tokens.get("scope", ""),
            "access_valid": time.time() < tokens["expires_at"],
            "access_expires_in": max(0, int(tokens["expires_at"] - time.time())),
            "refresh_expires_in": max(0, int(tokens["refresh_expires_at"] - time.time())),
        }
