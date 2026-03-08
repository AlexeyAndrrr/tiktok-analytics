from datetime import datetime

from tiktok_client.web_client import TikTokWebClient
from tiktok_client.unofficial_client import TikTokUnofficialClient
from db.models import Account, Video, VideoMetricsSnapshot
from db.database import db


class VideoCollector:
    """Collects video metadata and metrics snapshots for a specific account."""

    def __init__(self, account: Account, web_client: TikTokWebClient,
                 unofficial: TikTokUnofficialClient | None = None):
        self.account = account
        self.web_client = web_client
        self.unofficial = unofficial

    async def collect(self) -> tuple[int, int]:
        """Fetch all videos and their metrics. Returns (new_videos, snapshots)."""
        try:
            return await self._collect_web()
        except Exception as e:
            if self.unofficial:
                return await self._collect_unofficial()
            raise RuntimeError(f"Failed to collect videos: {e}")

    async def _collect_web(self) -> tuple[int, int]:
        """Collect videos via TikTok web API (includes inline metrics)."""
        sec_uid = self.account.sec_uid
        if not sec_uid:
            # Try to get sec_uid from profile
            username = self.account.username or self.account.login_id
            user_info = await self.web_client.get_user_info(username)
            sec_uid = user_info.get("sec_uid", "")
            if sec_uid:
                self.account.sec_uid = sec_uid
                self.account.save()

        if not sec_uid:
            raise RuntimeError("Cannot list videos without sec_uid. Collect profile first.")

        raw_videos = await self.web_client.list_all_videos(sec_uid)
        new_count = 0
        now = datetime.utcnow()

        with db.atomic():
            for v in raw_videos:
                create_time = v.get("create_time")
                if isinstance(create_time, (int, float)):
                    create_time = datetime.utcfromtimestamp(create_time)

                _, created = Video.get_or_create(
                    id=v["id"],
                    defaults={
                        "account": self.account,
                        "title": v.get("title", ""),
                        "video_description": v.get("video_description", ""),
                        "create_time": create_time,
                        "cover_image_url": v.get("cover_image_url"),
                        "share_url": v.get("share_url"),
                        "duration": v.get("duration"),
                        "height": v.get("height"),
                        "width": v.get("width"),
                    },
                )
                if created:
                    new_count += 1

                # Web API returns metrics inline — create snapshot immediately
                VideoMetricsSnapshot.create(
                    video=v["id"],
                    account=self.account,
                    collected_at=now,
                    view_count=v.get("view_count", 0),
                    like_count=v.get("like_count", 0),
                    comment_count=v.get("comment_count", 0),
                    share_count=v.get("share_count", 0),
                )

        return new_count, len(raw_videos)

    async def _collect_unofficial(self) -> tuple[int, int]:
        raw_videos = await self.unofficial.get_user_videos()
        new_count = 0
        now = datetime.utcnow()

        with db.atomic():
            for v in raw_videos:
                create_time = v.get("create_time")
                if isinstance(create_time, (int, float)):
                    create_time = datetime.utcfromtimestamp(create_time)

                _, created = Video.get_or_create(
                    id=v["id"],
                    defaults={
                        "account": self.account,
                        "title": v.get("title", ""),
                        "create_time": create_time,
                        "cover_image_url": v.get("cover_image_url"),
                        "duration": v.get("duration"),
                    },
                )
                if created:
                    new_count += 1

                VideoMetricsSnapshot.create(
                    video=v["id"],
                    account=self.account,
                    collected_at=now,
                    view_count=v.get("view_count", 0),
                    like_count=v.get("like_count", 0),
                    comment_count=v.get("comment_count", 0),
                    share_count=v.get("share_count", 0),
                )

        return new_count, len(raw_videos)
