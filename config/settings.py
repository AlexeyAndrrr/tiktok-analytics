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

# Database
DB_PATH = DATA_DIR / "tiktok_analytics.db"

# Tokens (per-account storage)
TOKENS_DIR = DATA_DIR / "tokens"
TOKENS_DIR.mkdir(parents=True, exist_ok=True)
TOKEN_ENCRYPTION_KEY = os.getenv("TOKEN_ENCRYPTION_KEY", "default-insecure-key")

# Browser automation
BROWSER_HEADLESS = os.getenv("BROWSER_HEADLESS", "true").lower() == "true"
BROWSER_PROFILES_DIR = DATA_DIR / "browser_profiles"
BROWSER_PROFILES_DIR.mkdir(parents=True, exist_ok=True)
BROWSER_LOGIN_TIMEOUT = int(os.getenv("BROWSER_LOGIN_TIMEOUT", "120"))

# Collection
COLLECTION_INTERVAL_HOURS = int(os.getenv("COLLECTION_INTERVAL_HOURS", "6"))
VIDEO_BATCH_SIZE = 20  # TikTok API limit per request

# Optional
TIKTOK_USERNAME = os.getenv("TIKTOK_USERNAME", "")
