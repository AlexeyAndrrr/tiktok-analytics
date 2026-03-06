import pandas as pd
from db.models import Account, ProfileSnapshot, Video, VideoMetricsSnapshot
from db.database import db


class AnalyticsEngine:
    """Computes analytics from collected TikTok data, scoped by account."""

    def __init__(self, account_id: int | None = None):
        self.account_id = account_id

    def _profile_query(self):
        q = ProfileSnapshot.select()
        if self.account_id:
            q = q.where(ProfileSnapshot.account == self.account_id)
        return q

    def _video_query(self):
        q = Video.select()
        if self.account_id:
            q = q.where(Video.account == self.account_id)
        return q

    def _metrics_query(self):
        q = VideoMetricsSnapshot.select()
        if self.account_id:
            q = q.where(VideoMetricsSnapshot.account == self.account_id)
        return q

    def follower_growth(self, days: int = 30) -> pd.DataFrame:
        query = (self._profile_query()
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
        query = (self._profile_query()
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
        return self._top_videos("view_count", limit)

    def top_videos_by_engagement_rate(self, limit: int = 10) -> pd.DataFrame:
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
        latest = (self._metrics_query()
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
        df = df.drop_duplicates(subset=["video"], keep="first")

        video_q = self._video_query()
        video_titles = {v.id: v.title for v in video_q}
        df["title"] = df["video"].map(video_titles)

        df["engagement_rate"] = df.apply(
            lambda r: ((r["like_count"] + r["comment_count"] + r["share_count"])
                       / max(r["view_count"], 1) * 100),
            axis=1,
        )
        return df.nlargest(limit, sort_field).reset_index(drop=True)

    def growth_rate(self, metric: str, days: int = 7) -> float | None:
        snapshots = (self._profile_query()
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
        latest = (self._profile_query()
                  .order_by(ProfileSnapshot.collected_at.desc())
                  .first())
        if not latest:
            return None
        total_snapshots = self._profile_query().count()
        total_metrics = self._metrics_query().count()

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

    # ── Comparison methods ─────────────────────────────

    @staticmethod
    def compare_summary(account_ids: list[int]) -> list[dict]:
        """Side-by-side summary stats for multiple accounts."""
        results = []
        for aid in account_ids:
            engine = AnalyticsEngine(account_id=aid)
            stats = engine.summary_stats()
            if stats:
                stats["account_id"] = aid
                stats["growth_7d"] = engine.growth_rate("follower_count", days=7)
                stats["growth_30d"] = engine.growth_rate("follower_count", days=30)
                results.append(stats)
        return results

    @staticmethod
    def compare_followers(account_ids: list[int], days: int = 30) -> dict:
        """Follower growth data for multiple accounts, keyed by account_id."""
        result = {}
        for aid in account_ids:
            engine = AnalyticsEngine(account_id=aid)
            df = engine.follower_growth(days=days)
            account = Account.get_or_none(Account.id == aid)
            label = account.username or account.display_name if account else str(aid)

            if not df.empty:
                result[label] = [
                    {"date": row["collected_at"].isoformat(), "followers": int(row["follower_count"])}
                    for _, row in df.iterrows()
                ]
            else:
                result[label] = []
        return result

    @staticmethod
    def compare_engagement(account_ids: list[int]) -> list[dict]:
        """Engagement comparison across accounts."""
        results = []
        for aid in account_ids:
            engine = AnalyticsEngine(account_id=aid)
            df = engine._top_videos("view_count", limit=1000)
            account = Account.get_or_none(Account.id == aid)

            entry = {
                "account_id": aid,
                "username": account.username if account else "",
                "display_name": account.display_name if account else "",
                "total_views": int(df["view_count"].sum()) if not df.empty else 0,
                "total_likes": int(df["like_count"].sum()) if not df.empty else 0,
                "total_comments": int(df["comment_count"].sum()) if not df.empty else 0,
                "total_shares": int(df["share_count"].sum()) if not df.empty else 0,
                "avg_engagement_rate": round(df["engagement_rate"].mean(), 2) if not df.empty else 0,
                "video_count": len(df) if not df.empty else 0,
            }
            results.append(entry)
        return results
