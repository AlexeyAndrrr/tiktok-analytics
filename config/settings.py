import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# On Vercel, use /tmp for writable storage
IS_VERCEL = os.getenv("VERCEL", "") == "1"
if IS_VERCEL:
    DATA_DIR = Path("/tmp/data")
else:
    DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE_DIR / ".env")

# TikTok API
TIKTOK_CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY", "")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET", "")
TIKTOK_API_BASE = "https://open.tiktokapis.com/v2"
TIKTOK_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"

# OAuth — auto-detect redirect URI on Vercel
VERCEL_URL = os.getenv("VERCEL_URL", "")
if VERCEL_URL and not os.getenv("OAUTH_REDIRECT_URI"):
    OAUTH_REDIRECT_URI = f"https://{VERCEL_URL}/api/auth/callback"
else:
    OAUTH_REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "http://localhost:3000/api/auth/callback")
OAUTH_PORT = int(os.getenv("OAUTH_PORT", "3000"))
OAUTH_SCOPES = "user.info.basic,user.info.profile,user.info.stats,video.list"

# Database
DB_PATH = DATA_DIR / "tiktok_analytics.db"

# Tokens
TOKEN_PATH = DATA_DIR / "tokens.json"
TOKEN_ENCRYPTION_KEY = os.getenv("TOKEN_ENCRYPTION_KEY", "default-insecure-key")

# Collection
COLLECTION_INTERVAL_HOURS = int(os.getenv("COLLECTION_INTERVAL_HOURS", "6"))
VIDEO_BATCH_SIZE = 20  # TikTok API limit per request

# Optional
TIKTOK_USERNAME = os.getenv("TIKTOK_USERNAME", "")
