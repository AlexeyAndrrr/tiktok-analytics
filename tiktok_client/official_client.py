import httpx
from datetime import datetime

from auth.token_manager import TokenManager
from tiktok_client.rate_limiter import RateLimiter
from config import settings


class TikTokOfficialClient:
    """TikTok API v2 client for authenticated user data."""

    BASE_URL = settings.TIKTOK_API_BASE

    def __init__(self, token_manager: TokenManager):
        self.token_manager = token_manager
        self.rate_limiter = RateLimiter()
        self._client = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30)
        return self._client

    def _auth_headers(self) -> dict:
        token = self.token_manager.get_access_token()
        return {"Authorization": f"Bearer {token}"}

    async def _request(self, method: str, url: str, **kwargs) -> dict:
        """Make an authenticated request with rate limiting and retry."""
        client = await self._get_client()

        for attempt in range(3):
            await self.rate_limiter.acquire()
            resp = await client.request(method, url, headers=self._auth_headers(), **kwargs)

            if resp.status_code == 429:
                await self.rate_limiter.backoff(attempt)
                continue

            resp.raise_for_status()
            data = resp.json()

            if data.get("error", {}).get("code") == "ok" or "data" in data:
                return data
            raise ValueError(f"API error: {data}")

        raise RuntimeError("Max retries exceeded")

    async def get_user_info(self) -> dict:
        """Fetch authenticated user's profile info."""
        fields = "open_id,display_name,username,bio_description,avatar_url,is_verified,follower_count,following_count,likes_count,video_count"
        data = await self._request(
            "GET",
            f"{self.BASE_URL}/user/info/",
            params={"fields": fields},
        )
        return data.get("data", {}).get("user", {})

    async def list_videos(self, cursor: int | None = None, max_count: int = 20) -> dict:
        """Fetch a page of the user's videos."""
        fields = "id,title,video_description,create_time,cover_image_url,share_url,duration,height,width"
        body = {"max_count": max_count}
        if cursor is not None:
            body["cursor"] = cursor

        data = await self._request(
            "POST",
            f"{self.BASE_URL}/video/list/",
            params={"fields": fields},
            json=body,
        )
        return data.get("data", {})

    async def list_all_videos(self) -> list[dict]:
        """Paginate through all user's videos."""
        all_videos = []
        cursor = None
        has_more = True

        while has_more:
            result = await self.list_videos(cursor=cursor)
            videos = result.get("videos", [])
            all_videos.extend(videos)
            has_more = result.get("has_more", False)
            cursor = result.get("cursor")

        return all_videos

    async def query_video_metrics(self, video_ids: list[str]) -> list[dict]:
        """Query engagement metrics for a list of video IDs (max 20 per call)."""
        all_metrics = []
        fields = "id,like_count,comment_count,share_count,view_count"

        for i in range(0, len(video_ids), settings.VIDEO_BATCH_SIZE):
            batch = video_ids[i:i + settings.VIDEO_BATCH_SIZE]
            body = {"filters": {"video_ids": batch}}

            data = await self._request(
                "POST",
                f"{self.BASE_URL}/video/query/",
                params={"fields": fields},
                json=body,
            )
            videos = data.get("data", {}).get("videos", [])
            all_metrics.extend(videos)

        return all_metrics

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
