import asyncio
import logging
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from auth.token_manager import TokenManager
from tiktok_client.official_client import TikTokOfficialClient
from tiktok_client.unofficial_client import TikTokUnofficialClient
from collectors.profile_collector import ProfileCollector
from collectors.video_collector import VideoCollector
from db.models import CollectionLog
from db.database import db, init_db
from config import settings

logger = logging.getLogger(__name__)


def _run_collection():
    """Synchronous wrapper for async collection."""
    asyncio.run(_async_collect())


async def _async_collect():
    """Run a full collection cycle."""
    init_db()
    token_manager = TokenManager()
    official = TikTokOfficialClient(token_manager)
    unofficial = TikTokUnofficialClient(settings.TIKTOK_USERNAME) if settings.TIKTOK_USERNAME else None

    profile_collector = ProfileCollector(official, unofficial)
    video_collector = VideoCollector(official, unofficial)

    log = CollectionLog.create(started_at=datetime.utcnow(), status="running")

    try:
        profile = await profile_collector.collect()
        new_videos, snapshots = await video_collector.collect()

        log.status = "success"
        log.videos_collected = snapshots
        log.completed_at = datetime.utcnow()
        log.save()

        logger.info(
            f"Collection complete: {profile.display_name} | "
            f"{profile.follower_count} followers | "
            f"{new_videos} new videos | {snapshots} metric snapshots"
        )

    except Exception as e:
        log.status = "failed"
        log.error_message = str(e)
        log.completed_at = datetime.utcnow()
        log.save()
        logger.error(f"Collection failed: {e}")

    finally:
        await official.close()
        if unofficial:
            await unofficial.close()


class CollectionScheduler:
    """Periodic data collection using APScheduler."""

    def __init__(self, interval_hours: int | None = None):
        self.interval_hours = interval_hours or settings.COLLECTION_INTERVAL_HOURS

    def start(self):
        """Start the scheduler (blocks until Ctrl+C)."""
        scheduler = BlockingScheduler()
        scheduler.add_job(
            _run_collection,
            trigger=IntervalTrigger(hours=self.interval_hours),
            id="tiktok_collection",
            name="TikTok Data Collection",
            next_run_time=datetime.utcnow(),  # Run immediately on start
        )

        logger.info(f"Scheduler started. Collecting every {self.interval_hours} hours. Press Ctrl+C to stop.")
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Scheduler stopped.")
