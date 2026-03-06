from datetime import datetime
from peewee import (
    Model, AutoField, CharField, TextField, IntegerField,
    BooleanField, DateTimeField, ForeignKeyField, FloatField,
)
from db.database import db


class BaseModel(Model):
    class Meta:
        database = db


class ProfileSnapshot(BaseModel):
    id = AutoField()
    collected_at = DateTimeField(default=datetime.utcnow)
    open_id = CharField()
    display_name = CharField(default="")
    username = CharField(null=True)
    bio_description = TextField(null=True)
    avatar_url = CharField(null=True)
    is_verified = BooleanField(default=False)
    follower_count = IntegerField(default=0)
    following_count = IntegerField(default=0)
    likes_count = IntegerField(default=0)
    video_count = IntegerField(default=0)

    class Meta:
        table_name = "profile_snapshots"


class Video(BaseModel):
    id = CharField(primary_key=True)
    title = TextField(null=True)
    video_description = TextField(null=True)
    create_time = DateTimeField(null=True)
    cover_image_url = CharField(null=True)
    share_url = CharField(null=True)
    duration = IntegerField(null=True)
    height = IntegerField(null=True)
    width = IntegerField(null=True)
    first_seen_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "videos"


class VideoMetricsSnapshot(BaseModel):
    id = AutoField()
    video = ForeignKeyField(Video, backref="metrics_snapshots", on_delete="CASCADE")
    collected_at = DateTimeField(default=datetime.utcnow)
    view_count = IntegerField(default=0)
    like_count = IntegerField(default=0)
    comment_count = IntegerField(default=0)
    share_count = IntegerField(default=0)

    class Meta:
        table_name = "video_metrics_snapshots"
        indexes = (
            (("video", "collected_at"), False),
        )


class CollectionLog(BaseModel):
    id = AutoField()
    started_at = DateTimeField(default=datetime.utcnow)
    completed_at = DateTimeField(null=True)
    status = CharField(default="running")  # running, success, partial, failed
    source = CharField(default="official_api")
    videos_collected = IntegerField(default=0)
    error_message = TextField(null=True)

    class Meta:
        table_name = "collection_logs"
