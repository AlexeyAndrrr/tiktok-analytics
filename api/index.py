import sys
import os
import json
import asyncio
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, jsonify, redirect, request, session, url_for
from config import settings
from db.database import init_db
from db.models import ProfileSnapshot, Video, VideoMetricsSnapshot, CollectionLog

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates"),
    static_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), "static"),
)
app.secret_key = settings.TOKEN_ENCRYPTION_KEY


@app.before_request
def setup_db():
    init_db()


# ── Pages ──────────────────────────────────────────────

@app.route("/")
def dashboard():
    """Main dashboard page."""
    return render_template("dashboard.html")


@app.route("/login")
def login_page():
    """OAuth login page."""
    return render_template("login.html")


# ── Auth API ───────────────────────────────────────────

@app.route("/api/auth/login")
def auth_login():
    """Start OAuth2 flow — redirect to TikTok."""
    if not settings.TIKTOK_CLIENT_KEY or settings.TIKTOK_CLIENT_KEY == "your_client_key_here":
        return jsonify({"error": "TIKTOK_CLIENT_KEY not configured"}), 500

    from auth.oauth_server import OAuthCallbackServer
    server = OAuthCallbackServer()

    # Store PKCE verifier in session
    session["code_verifier"] = server.code_verifier
    session["oauth_state"] = server.state

    return redirect(server.get_authorization_url())


@app.route("/api/auth/callback")
def auth_callback():
    """Handle OAuth2 callback from TikTok."""
    error = request.args.get("error")
    if error:
        return render_template("login.html", error=f"{error}: {request.args.get('error_description', '')}")

    state = request.args.get("state")
    if state != session.get("oauth_state"):
        return render_template("login.html", error="State mismatch — possible CSRF attack")

    code = request.args.get("code")
    if not code:
        return render_template("login.html", error="No authorization code received")

    from auth.token_manager import TokenManager
    tm = TokenManager()

    try:
        tm.exchange_code(code, session.get("code_verifier", ""))
        return redirect("/")
    except Exception as e:
        return render_template("login.html", error=str(e))


@app.route("/api/auth/status")
def auth_status():
    """Check authentication status."""
    from auth.token_manager import TokenManager
    tm = TokenManager()
    info = tm.status()
    if not info:
        return jsonify({"authenticated": False})
    return jsonify({"authenticated": True, **info})


@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    """Revoke tokens and log out."""
    from auth.token_manager import TokenManager
    tm = TokenManager()
    tm.revoke()
    return jsonify({"ok": True})


# ── Data API ───────────────────────────────────────────

@app.route("/api/collect", methods=["POST"])
def collect_now():
    """Trigger immediate data collection."""
    from auth.token_manager import TokenManager
    from tiktok_client.official_client import TikTokOfficialClient
    from tiktok_client.unofficial_client import TikTokUnofficialClient
    from collectors.profile_collector import ProfileCollector
    from collectors.video_collector import VideoCollector

    tm = TokenManager()
    if not tm.load():
        return jsonify({"error": "Not authenticated"}), 401

    async def _collect():
        official = TikTokOfficialClient(tm)
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

            return {
                "status": "success",
                "profile": profile.display_name,
                "followers": profile.follower_count,
                "new_videos": new_videos,
                "snapshots": snapshots,
            }
        except Exception as e:
            log.status = "failed"
            log.error_message = str(e)
            log.completed_at = datetime.utcnow()
            log.save()
            return {"status": "failed", "error": str(e)}
        finally:
            await official.close()
            if unofficial:
                await unofficial.close()

    result = asyncio.run(_collect())
    status_code = 200 if result["status"] == "success" else 500
    return jsonify(result), status_code


@app.route("/api/summary")
def api_summary():
    """Get account summary stats."""
    from reports.analytics import AnalyticsEngine
    engine = AnalyticsEngine()
    stats = engine.summary_stats()
    if not stats:
        return jsonify({"error": "No data yet"}), 404
    growth_7d = engine.growth_rate("follower_count", days=7)
    growth_30d = engine.growth_rate("follower_count", days=30)
    stats["growth_7d"] = growth_7d
    stats["growth_30d"] = growth_30d
    return jsonify(stats)


@app.route("/api/growth")
def api_growth():
    """Get follower growth data."""
    days = request.args.get("days", 30, type=int)
    from reports.analytics import AnalyticsEngine
    engine = AnalyticsEngine()

    df = engine.follower_growth(days=days)
    if df.empty:
        return jsonify([])

    data = []
    for _, row in df.iterrows():
        data.append({
            "date": row["collected_at"].isoformat(),
            "followers": int(row["follower_count"]),
        })
    return jsonify(data)


@app.route("/api/likes-growth")
def api_likes_growth():
    """Get likes growth data."""
    days = request.args.get("days", 30, type=int)
    from reports.analytics import AnalyticsEngine
    engine = AnalyticsEngine()

    df = engine.likes_growth(days=days)
    if df.empty:
        return jsonify([])

    data = []
    for _, row in df.iterrows():
        data.append({
            "date": row["collected_at"].isoformat(),
            "likes": int(row["likes_count"]),
        })
    return jsonify(data)


@app.route("/api/top-videos")
def api_top_videos():
    """Get top videos."""
    limit = request.args.get("limit", 10, type=int)
    sort = request.args.get("sort", "views")

    from reports.analytics import AnalyticsEngine
    engine = AnalyticsEngine()

    if sort == "engagement":
        df = engine.top_videos_by_engagement_rate(limit=limit)
    else:
        df = engine.top_videos_by_views(limit=limit)

    if df.empty:
        return jsonify([])

    videos = []
    for _, row in df.iterrows():
        videos.append({
            "title": str(row.get("title", ""))[:60] or "(no title)",
            "views": int(row["view_count"]),
            "likes": int(row["like_count"]),
            "comments": int(row["comment_count"]),
            "shares": int(row["share_count"]),
            "engagement_rate": round(row.get("engagement_rate", 0), 2),
        })
    return jsonify(videos)


@app.route("/api/collection-history")
def api_collection_history():
    """Get collection log."""
    limit = request.args.get("limit", 10, type=int)
    logs = (CollectionLog
            .select()
            .order_by(CollectionLog.started_at.desc())
            .limit(limit))

    result = []
    for log in logs:
        duration = ""
        if log.completed_at and log.started_at:
            delta = log.completed_at - log.started_at
            duration = f"{delta.total_seconds():.1f}s"

        result.append({
            "date": str(log.started_at)[:19],
            "status": log.status,
            "videos": log.videos_collected,
            "duration": duration,
            "error": (log.error_message or "")[:100],
        })
    return jsonify(result)


# ── Vercel Cron ────────────────────────────────────────

@app.route("/api/cron/collect")
def cron_collect():
    """Endpoint for Vercel Cron to trigger collection."""
    # Verify cron secret
    auth_header = request.headers.get("Authorization")
    cron_secret = os.getenv("CRON_SECRET", "")
    if cron_secret and auth_header != f"Bearer {cron_secret}":
        return jsonify({"error": "Unauthorized"}), 401

    # Reuse collect logic
    with app.test_request_context():
        return collect_now()


if __name__ == "__main__":
    app.run(debug=True, port=3000)
