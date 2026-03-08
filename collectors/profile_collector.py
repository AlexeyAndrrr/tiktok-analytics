from datetime import datetime

from tiktok_client.web_client import TikTokWebClient
from tiktok_client.unofficial_client import TikTokUnofficialClient
from db.models import Account, ProfileSnapshot
from db.database import db


class ProfileCollector:
    """Collects and stores profile snapshots for a specific account."""

    def __init__(self, account: Account, web_client: TikTokWebClient,
                 unofficial: TikTokUnofficialClient | None = None):
        self.account = account
        self.web_client = web_client
        self.unofficial = unofficial

    async def collect(self) -> ProfileSnapshot:
        """Fetch profile data and save a snapshot."""
        username = self.account.username or self.account.login_id

        try:
            user = await self.web_client.get_user_info(username)
        except Exception as e:
            if self.unofficial:
                user = await self.unofficial.get_user_info()
            else:
                raise RuntimeError(f"Failed to fetch profile: {e}")

        # Update account info
        self.account.display_name = user.get("display_name", "")
        self.account.username = user.get("username")
        self.account.avatar_url = user.get("avatar_url")
        self.account.open_id = user.get("open_id", self.account.open_id or "")
        # Store sec_uid for video listing
        sec_uid = user.get("sec_uid")
        if sec_uid:
            self.account.sec_uid = sec_uid
        self.account.save()

        with db.atomic():
            snapshot = ProfileSnapshot.create(
                account=self.account,
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
