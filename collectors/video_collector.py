from datetime import datetime

from tiktok_client.official_client import TikTokOfficialClient
from tiktok_client.unofficial_client import TikTokUnofficialClient
from db.models import Account, Video, VideoMetricsSnapshot
from db.database import db


class VideoCollector:
    """Collects video metadata and metrics snapshots for a specific account."""

    def __init__(self, account: Account, official: TikTokOfficialClient,
                 unofficial: TikTokUnofficialClient | None = None):
        self.account = account
        self.official = official
        self.unofficial = unofficial

    async def collect(self) -> tuple[int, int]:
        """Fetch all videos and their metrics. Returns (new_videos, snapshots)."""
        try:
            return await self._collect_official()
        except Exception as e:
            if self.unofficial:
                return await self._collect_unofficial()
            raise RuntimeError(f"Failed to collect videos: {e}")

    async def _collect_official(self) -> tuple[int, int]:
        raw_videos = await self.official.list_all_videos()
        new_count = 0

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

        video_ids = [v["id"] for v in raw_videos]
        if not video_ids:
            return new_count, 0

        metrics = await self.official.query_video_metrics(video_ids)
        now = datetime.utcnow()
        snapshot_count = 0

        with db.atomic():
            for m in metrics:
                VideoMetricsSnapshot.create(
                    video=m["id"],
                    account=self.account,
                    collected_at=now,
                    view_count=m.get("view_count", 0),
                    like_count=m.get("like_count", 0),
                    comment_count=m.get("comment_count", 0),
                    share_count=m.get("share_count", 0),
                )
                snapshot_count += 1

        return new_count, snapshot_count

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
