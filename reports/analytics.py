import pandas as pd
from db.models import ProfileSnapshot, Video, VideoMetricsSnapshot
from db.database import db


class AnalyticsEngine:
    """Computes analytics from collected TikTok data."""

    def follower_growth(self, days: int = 30) -> pd.DataFrame:
        """Time series of follower count."""
        query = (ProfileSnapshot
                 .select(ProfileSnapshot.collected_at, ProfileSnapshot.follower_count)
                 .order_by(ProfileSnapshot.collected_at)
                 .dicts())

        df = pd.DataFrame(list(query))
        if df.empty:
            return df

        df["collected_at"] = pd.to_datetime(df["collected_at"])
        cutoff = df["collected_at"].max() - pd.Timedelta(days=days)
        return df[df["collected_at"] >= cutoff].reset_index(drop=True)

    def likes_growth(self, days: int = 30) -> pd.DataFrame:
        """Time series of total likes."""
        query = (ProfileSnapshot
                 .select(ProfileSnapshot.collected_at, ProfileSnapshot.likes_count)
                 .order_by(ProfileSnapshot.collected_at)
                 .dicts())

        df = pd.DataFrame(list(query))
        if df.empty:
            return df

        df["collected_at"] = pd.to_datetime(df["collected_at"])
        cutoff = df["collected_at"].max() - pd.Timedelta(days=days)
        return df[df["collected_at"] >= cutoff].reset_index(drop=True)

    def top_videos_by_views(self, limit: int = 10) -> pd.DataFrame:
        """Top videos by view count (latest metrics snapshot)."""
        return self._top_videos("view_count", limit)

    def top_videos_by_engagement_rate(self, limit: int = 10) -> pd.DataFrame:
        """Top videos by engagement rate."""
        df = self._top_videos("view_count", limit=100)
        if df.empty:
            return df

        df["engagement_rate"] = df.apply(
            lambda r: ((r["like_count"] + r["comment_count"] + r["share_count"])
                       / max(r["view_count"], 1) * 100),
            axis=1,
        )
        return df.nlargest(limit, "engagement_rate").reset_index(drop=True)

    def _top_videos(self, sort_field: str, limit: int) -> pd.DataFrame:
        """Get latest metrics for each video, sorted by a field."""
        # Subquery: latest snapshot per video
        latest = (VideoMetricsSnapshot
                  .select(
                      VideoMetricsSnapshot.video,
                      VideoMetricsSnapshot.view_count,
                      VideoMetricsSnapshot.like_count,
                      VideoMetricsSnapshot.comment_count,
                      VideoMetricsSnapshot.share_count,
                      VideoMetricsSnapshot.collected_at,
                  )
                  .join(Video)
                  .switch(VideoMetricsSnapshot)
                  .order_by(VideoMetricsSnapshot.collected_at.desc())
                  .dicts())

        df = pd.DataFrame(list(latest))
        if df.empty:
            return df

        # Keep only the latest snapshot per video
        df = df.drop_duplicates(subset=["video"], keep="first")

        # Add video title
        video_titles = {v.id: v.title for v in Video.select()}
        df["title"] = df["video"].map(video_titles)

        # Calculate engagement rate
        df["engagement_rate"] = df.apply(
            lambda r: ((r["like_count"] + r["comment_count"] + r["share_count"])
                       / max(r["view_count"], 1) * 100),
            axis=1,
        )

        return df.nlargest(limit, sort_field).reset_index(drop=True)

    def video_performance_over_time(self, video_id: str) -> pd.DataFrame:
        """Time series of a specific video's metrics."""
        query = (VideoMetricsSnapshot
                 .select()
                 .where(VideoMetricsSnapshot.video == video_id)
                 .order_by(VideoMetricsSnapshot.collected_at)
                 .dicts())

        df = pd.DataFrame(list(query))
        if not df.empty:
            df["collected_at"] = pd.to_datetime(df["collected_at"])
        return df

    def posting_frequency(self, days: int = 90) -> pd.DataFrame:
        """Videos posted per week."""
        query = Video.select(Video.create_time).where(Video.create_time.is_null(False)).dicts()
        df = pd.DataFrame(list(query))
        if df.empty:
            return df

        df["create_time"] = pd.to_datetime(df["create_time"])
        cutoff = df["create_time"].max() - pd.Timedelta(days=days)
        df = df[df["create_time"] >= cutoff]

        df["week"] = df["create_time"].dt.isocalendar().week
        weekly = df.groupby("week").size().reset_index(name="count")
        return weekly

    def best_posting_times(self) -> pd.DataFrame:
        """Correlate posting hour/day with average engagement."""
        videos = pd.DataFrame(list(
            Video.select(Video.id, Video.create_time)
            .where(Video.create_time.is_null(False))
            .dicts()
        ))
        if videos.empty:
            return videos

        metrics = pd.DataFrame(list(
            VideoMetricsSnapshot.select().dicts()
        ))
        if metrics.empty:
            return pd.DataFrame()

        # Latest metrics per video
        metrics = metrics.sort_values("collected_at").drop_duplicates(subset=["video"], keep="last")

        merged = videos.merge(metrics, left_on="id", right_on="video", how="inner")
        merged["create_time"] = pd.to_datetime(merged["create_time"])
        merged["hour"] = merged["create_time"].dt.hour
        merged["day_of_week"] = merged["create_time"].dt.day_name()

        merged["engagement"] = (merged["like_count"] + merged["comment_count"] + merged["share_count"])

        return (merged
                .groupby(["day_of_week", "hour"])
                .agg(avg_engagement=("engagement", "mean"), count=("id", "count"))
                .reset_index())

    def growth_rate(self, metric: str, days: int = 7) -> float | None:
        """Percentage change in a metric over the last N days."""
        snapshots = (ProfileSnapshot
                     .select(ProfileSnapshot.collected_at, getattr(ProfileSnapshot, metric))
                     .order_by(ProfileSnapshot.collected_at)
                     .dicts())

        df = pd.DataFrame(list(snapshots))
        if len(df) < 2:
            return None

        df["collected_at"] = pd.to_datetime(df["collected_at"])
        cutoff = df["collected_at"].max() - pd.Timedelta(days=days)
        old = df[df["collected_at"] <= cutoff]

        if old.empty:
            return None

        old_val = old.iloc[-1][metric]
        new_val = df.iloc[-1][metric]

        if old_val == 0:
            return None
        return ((new_val - old_val) / old_val) * 100

    def summary_stats(self) -> dict | None:
        """Overview statistics."""
        latest = (ProfileSnapshot
                  .select()
                  .order_by(ProfileSnapshot.collected_at.desc())
                  .first())

        if not latest:
            return None

        total_snapshots = ProfileSnapshot.select().count()
        total_metrics = VideoMetricsSnapshot.select().count()

        # Average views and engagement
        df = self._top_videos("view_count", limit=1000)
        avg_views = df["view_count"].mean() if not df.empty else 0
        avg_engagement = df["engagement_rate"].mean() if not df.empty and "engagement_rate" in df else 0
        best_views = int(df["view_count"].max()) if not df.empty else 0

        return {
            "display_name": latest.display_name,
            "username": latest.username or "",
            "follower_count": latest.follower_count,
            "following_count": latest.following_count,
            "likes_count": latest.likes_count,
            "video_count": latest.video_count,
            "avg_views": avg_views,
            "avg_engagement_rate": avg_engagement,
            "best_video_views": best_views,
            "total_snapshots": total_snapshots,
            "total_metric_snapshots": total_metrics,
        }
