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
from db.models import Account, CollectionLog
from db.database import db, init_db
from config import settings

logger = logging.getLogger(__name__)


def _run_collection():
    """Synchronous wrapper for async collection of ALL accounts."""
    asyncio.run(_async_collect_all())


async def _async_collect_all():
    """Run collection for all registered accounts."""
    init_db()
    tm = TokenManager()
    account_ids = tm.list_account_ids()

    if not account_ids:
        logger.warning("No accounts configured. Skipping collection.")
        return

    for account_id in account_ids:
        await _async_collect(account_id)


async def _async_collect(account_id: int):
    """Run a full collection cycle for a single account."""
    init_db()
    token_manager = TokenManager(account_id=account_id)

    account = Account.get_or_none(Account.id == account_id)
    if not account:
        logger.error(f"Account {account_id} not found in DB")
        return

    official = TikTokOfficialClient(token_manager)
    unofficial = TikTokUnofficialClient(account.username or "") if account.username else None

    profile_collector = ProfileCollector(account, official, unofficial)
    video_collector = VideoCollector(account, official, unofficial)

    log = CollectionLog.create(
        account=account,
        started_at=datetime.utcnow(),
        status="running",
    )

    try:
        profile = await profile_collector.collect()
        new_videos, snapshots = await video_collector.collect()

        log.status = "success"
        log.videos_collected = snapshots
        log.completed_at = datetime.utcnow()
        log.save()

        logger.info(
            f"[{account.display_name}] Collection complete: "
            f"{profile.follower_count} followers | "
            f"{new_videos} new videos | {snapshots} metric snapshots"
        )

    except Exception as e:
        log.status = "failed"
        log.error_message = str(e)
        log.completed_at = datetime.utcnow()
        log.save()
        logger.error(f"[Account {account_id}] Collection failed: {e}")

    finally:
        await official.close()
        if unofficial:
            await unofficial.close()


class CollectionScheduler:
    """Periodic data collection for all accounts using APScheduler."""

    def __init__(self, interval_hours: int | None = None):
        self.interval_hours = interval_hours or settings.COLLECTION_INTERVAL_HOURS

    def start(self):
        scheduler = BlockingScheduler()
        scheduler.add_job(
            _run_collection,
            trigger=IntervalTrigger(hours=self.interval_hours),
            id="tiktok_collection",
            name="TikTok Data Collection (all accounts)",
            next_run_time=datetime.utcnow(),
        )

        logger.info(f"Scheduler started. Collecting every {self.interval_hours} hours. Press Ctrl+C to stop.")
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Scheduler stopped.")
