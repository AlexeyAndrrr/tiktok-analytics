"""
Fallback client using the unofficial TikTokApi library.
Only accesses PUBLIC data — no auth required.
Used when the official API is unavailable or not yet set up.

Requires: pip install TikTokApi playwright
           python -m playwright install
"""


class TikTokUnofficialClient:
    """Fallback for public data via unofficial TikTok-Api library."""

    def __init__(self, username: str = ""):
        self.username = username
        self._api = None

    async def _get_api(self):
        if self._api is None:
            try:
                from TikTokApi import TikTokApi
                self._api = TikTokApi()
                await self._api.create_sessions(num_sessions=1, sleep_after=3)
            except ImportError:
                raise RuntimeError(
                    "TikTokApi not installed. Run: pip install TikTokApi && python -m playwright install"
                )
        return self._api

    async def get_user_info(self, username: str | None = None) -> dict:
        """Fetch public profile data."""
        username = username or self.username
        if not username:
            raise ValueError("Username required for unofficial API")

        api = await self._get_api()
        user = api.user(username=username)
        user_data = await user.info()

        stats = user_data.get("userInfo", {}).get("stats", {})
        user_info = user_data.get("userInfo", {}).get("user", {})

        return {
            "display_name": user_info.get("nickname", ""),
            "username": username,
            "bio_description": user_info.get("signature", ""),
            "avatar_url": user_info.get("avatarLarger", ""),
            "is_verified": user_info.get("verified", False),
            "follower_count": stats.get("followerCount", 0),
            "following_count": stats.get("followingCount", 0),
            "likes_count": stats.get("heartCount", 0),
            "video_count": stats.get("videoCount", 0),
        }

    async def get_user_videos(self, username: str | None = None, count: int = 30) -> list[dict]:
        """Fetch public videos with available metrics."""
        username = username or self.username
        if not username:
            raise ValueError("Username required for unofficial API")

        api = await self._get_api()
        user = api.user(username=username)
        videos = []

        async for video in user.videos(count=count):
            video_data = video.as_dict
            stats = video_data.get("stats", {})
            videos.append({
                "id": video_data.get("id", ""),
                "title": video_data.get("desc", ""),
                "create_time": video_data.get("createTime", 0),
                "duration": video_data.get("video", {}).get("duration", 0),
                "cover_image_url": video_data.get("video", {}).get("cover", ""),
                "view_count": stats.get("playCount", 0),
                "like_count": stats.get("diggCount", 0),
                "comment_count": stats.get("commentCount", 0),
                "share_count": stats.get("shareCount", 0),
            })

        return videos

    async def close(self):
        if self._api:
            await self._api.close_sessions()
            self._api = None
