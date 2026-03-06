from peewee import SqliteDatabase
from config import settings

db = SqliteDatabase(str(settings.DB_PATH), pragmas={
    "journal_mode": "wal",
    "cache_size": -64 * 1000,  # 64MB
    "foreign_keys": 1,
})


def init_db():
    """Create all tables if they don't exist."""
    from db.models import Account, ProfileSnapshot, Video, VideoMetricsSnapshot, CollectionLog
    db.connect(reuse_if_open=True)
    db.create_tables([Account, ProfileSnapshot, Video, VideoMetricsSnapshot, CollectionLog])
