"""TikTok web API client using session cookies for authenticated access."""

import logging

import httpx

from tiktok_client.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class TikTokWebClient:
    """HTTP client that uses browser session cookies to access TikTok's internal web APIs."""

    BASE_URL = "https://www.tiktok.com/api"

    def __init__(self, cookies: dict):
        self.cookies = cookies
        self.rate_limiter = RateLimiter(requests_per_second=0.5, daily_limit=1000)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=30,
                cookies=self.cookies,
                headers={
                    "User-Agent": USER_AGENT,
                    "Referer": "https://www.tiktok.com/",
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "en-US,en;q=0.9",
                },
                follow_redirects=True,
            )
        return self._client

    async def _request(self, url: str, params: dict | None = None) -> dict:
        """Make a cookie-authenticated GET request with rate limiting."""
        client = await self._get_client()

        for attempt in range(3):
            await self.rate_limiter.acquire()
            try:
                resp = await client.get(url, params=params)
                if resp.status_code == 429:
                    logger.warning(f"Rate limited (429), backing off (attempt {attempt + 1})")
                    await self.rate_limiter.backoff(attempt)
                    continue
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                if attempt < 2:
                    logger.warning(f"HTTP {e.response.status_code}, retrying...")
                    await self.rate_limiter.backoff(attempt)
                    continue
                raise

        raise RuntimeError("Max retries exceeded for TikTok web API request")

    async def get_user_info(self, username: str) -> dict:
        """
        Fetch user profile info via TikTok's internal web API.

        Returns dict matching the format used by collectors:
            {open_id, display_name, username, bio_description, avatar_url,
             is_verified, follower_count, following_count, likes_count, video_count,
             sec_uid}
        """
        data = await self._request(
            f"{self.BASE_URL}/user/detail/",
            params={"uniqueId": username},
        )

        user_info = data.get("userInfo", {})
        user = user_info.get("user", {})
        stats = user_info.get("stats", {})

        return {
            "open_id": user.get("id", ""),
            "sec_uid": user.get("secUid", ""),
            "display_name": user.get("nickname", ""),
            "username": user.get("uniqueId", username),
            "bio_description": user.get("signature", ""),
            "avatar_url": user.get("avatarLarger", "") or user.get("avatarMedium", ""),
            "is_verified": user.get("verified", False),
            "follower_count": stats.get("followerCount", 0),
            "following_count": stats.get("followingCount", 0),
            "likes_count": stats.get("heartCount", 0) or stats.get("heart", 0),
            "video_count": stats.get("videoCount", 0),
        }

    async def list_all_videos(self, sec_uid: str) -> list[dict]:
        """
        Paginate through all user's videos via TikTok's internal web API.
        Returns videos with inline metrics (no separate metrics call needed).
        """
        all_videos = []
        cursor = 0
        has_more = True

        while has_more:
            data = await self._request(
                f"{self.BASE_URL}/post/item_list/",
                params={
                    "aid": "1988",
                    "count": "35",
                    "secUid": sec_uid,
                    "cursor": str(cursor),
                },
            )

            items = data.get("itemList", [])
            if not items:
                break

            for item in items:
                stats = item.get("stats", {})
                video_info = item.get("video", {})
                author = item.get("author", {})

                all_videos.append({
                    "id": item.get("id", ""),
                    "title": item.get("desc", ""),
                    "video_description": item.get("desc", ""),
                    "create_time": item.get("createTime", 0),
                    "cover_image_url": video_info.get("cover", "")
                                       or video_info.get("originCover", ""),
                    "share_url": (
                        f"https://www.tiktok.com/@{author.get('uniqueId', '')}"
                        f"/video/{item.get('id', '')}"
                    ),
                    "duration": video_info.get("duration", 0),
                    "height": video_info.get("height", 0),
                    "width": video_info.get("width", 0),
                    # Inline metrics
                    "view_count": stats.get("playCount", 0),
                    "like_count": stats.get("diggCount", 0),
                    "comment_count": stats.get("commentCount", 0),
                    "share_count": stats.get("shareCount", 0),
                })

            has_more = data.get("hasMore", False)
            cursor = data.get("cursor", cursor + len(items))

            logger.info(f"Fetched {len(items)} videos (total: {len(all_videos)})")

        return all_videos

    async def get_video_detail(self, video_id: str) -> dict:
        """Fetch detail for a single video."""
        data = await self._request(
            f"{self.BASE_URL}/item/detail/",
            params={"itemId": video_id},
        )

        item = data.get("itemInfo", {}).get("itemStruct", {})
        stats = item.get("stats", {})

        return {
            "id": video_id,
            "view_count": stats.get("playCount", 0),
            "like_count": stats.get("diggCount", 0),
            "comment_count": stats.get("commentCount", 0),
            "share_count": stats.get("shareCount", 0),
        }

    async def query_video_metrics(self, video_ids: list[str]) -> list[dict]:
        """
        Fetch metrics for multiple videos.
        Web API doesn't have batch endpoint — fetches individually.
        """
        metrics = []
        for vid_id in video_ids:
            try:
                detail = await self.get_video_detail(vid_id)
                metrics.append(detail)
            except Exception as e:
                logger.warning(f"Failed to fetch metrics for video {vid_id}: {e}")
                metrics.append({
                    "id": vid_id,
                    "view_count": 0,
                    "like_count": 0,
                    "comment_count": 0,
                    "share_count": 0,
                })
        return metrics

    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
