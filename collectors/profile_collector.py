from datetime import datetime

from tiktok_client.official_client import TikTokOfficialClient
from tiktok_client.unofficial_client import TikTokUnofficialClient
from db.models import ProfileSnapshot
from db.database import db


class ProfileCollector:
    """Collects and stores profile snapshots."""

    def __init__(self, official: TikTokOfficialClient, unofficial: TikTokUnofficialClient | None = None):
        self.official = official
        self.unofficial = unofficial

    async def collect(self) -> ProfileSnapshot:
        """Fetch profile data and save a snapshot."""
        try:
            user = await self.official.get_user_info()
            source = "official_api"
        except Exception as e:
            if self.unofficial:
                user = await self.unofficial.get_user_info()
                source = "unofficial_api"
            else:
                raise RuntimeError(f"Failed to fetch profile: {e}")

        with db.atomic():
            snapshot = ProfileSnapshot.create(
                collected_at=datetime.utcnow(),
                open_id=user.get("open_id", ""),
                display_name=user.get("display_name", ""),
                username=user.get("username"),
                bio_description=user.get("bio_description"),
                avatar_url=user.get("avatar_url"),
                is_verified=user.get("is_verified", False),
                follower_count=user.get("follower_count", 0),
                following_count=user.get("following_count", 0),
                likes_count=user.get("likes_count", 0),
                video_count=user.get("video_count", 0),
            )

        return snapshot
