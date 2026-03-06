import sys
import os
import json
import asyncio
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, jsonify, redirect, request, session
from config import settings
from db.database import init_db
from db.models import Account, ProfileSnapshot, Video, VideoMetricsSnapshot, CollectionLog

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates"),
    static_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), "static"),
)
app.secret_key = settings.TOKEN_ENCRYPTION_KEY


def _get_account_id():
    """Get account_id from query param or default to primary."""
    from auth.token_manager import TokenManager
    aid = request.args.get("account_id", type=int)
    if aid:
        return aid
    return TokenManager().get_primary_id()


@app.before_request
def setup_db():
    init_db()


# ── Pages ──────────────────────────────────────────────

@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/login")
def login_page():
    return render_template("login.html")


# ── Auth API ───────────────────────────────────────────

@app.route("/api/auth/login")
def auth_login():
    """Start OAuth2 flow — redirect to TikTok."""
    if not settings.TIKTOK_CLIENT_KEY or settings.TIKTOK_CLIENT_KEY == "your_client_key_here":
        return jsonify({"error": "TIKTOK_CLIENT_KEY not configured"}), 500

    from auth.oauth_server import OAuthCallbackServer
    server = OAuthCallbackServer()
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
        return render_template("login.html", error="State mismatch")

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
    from auth.token_manager import TokenManager
    tm = TokenManager()
    if not tm.has_any_accounts():
        return jsonify({"authenticated": False})
    info = tm.status()
    if not info:
        return jsonify({"authenticated": False})
    return jsonify({"authenticated": True, **info})


@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    """Revoke current account tokens."""
    account_id = request.json.get("account_id") if request.is_json else None
    from auth.token_manager import TokenManager
    tm = TokenManager(account_id=account_id)
    tm.revoke(account_id)
    return jsonify({"ok": True})


# ── Account management ────────────────────────────────

@app.route("/api/accounts")
def list_accounts():
    """List all connected accounts."""
    accounts = Account.select().order_by(Account.added_at)
    result = []
    for a in accounts:
        result.append({
            "id": a.id,
            "open_id": a.open_id,
            "display_name": a.display_name,
            "username": a.username or "",
            "avatar_url": a.avatar_url or "",
            "is_primary": a.is_primary,
        })
    return jsonify(result)


@app.route("/api/accounts/<int:account_id>/set-primary", methods=["POST"])
def set_primary_account(account_id):
    from auth.token_manager import TokenManager
    tm = TokenManager()
    tm.set_primary(account_id)
    return jsonify({"ok": True})


@app.route("/api/accounts/<int:account_id>/remove", methods=["POST"])
def remove_account(account_id):
    from auth.token_manager import TokenManager
    tm = TokenManager()
    tm.revoke(account_id)
    return jsonify({"ok": True})


# ── Data API (account-scoped) ─────────────────────────

@app.route("/api/collect", methods=["POST"])
def collect_now():
    """Trigger data collection for a specific or all accounts."""
    from auth.token_manager import TokenManager
    from tiktok_client.official_client import TikTokOfficialClient
    from tiktok_client.unofficial_client import TikTokUnofficialClient
    from collectors.profile_collector import ProfileCollector
    from collectors.video_collector import VideoCollector

    account_id = None
    if request.is_json:
        account_id = request.json.get("account_id")
    if not account_id:
        account_id = _get_account_id()
    if not account_id:
        return jsonify({"error": "No accounts configured"}), 400

    account = Account.get_or_none(Account.id == account_id)
    if not account:
        return jsonify({"error": "Account not found"}), 404

    tm = TokenManager(account_id=account_id)
    if not tm.load():
        return jsonify({"error": "Not authenticated"}), 401

    async def _collect():
        official = TikTokOfficialClient(tm)
        unofficial = None

        profile_collector = ProfileCollector(account, official, unofficial)
        video_collector = VideoCollector(account, official, unofficial)

        log = CollectionLog.create(account=account, started_at=datetime.utcnow(), status="running")

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

    result = asyncio.run(_collect())
    status_code = 200 if result["status"] == "success" else 500
    return jsonify(result), status_code


@app.route("/api/summary")
def api_summary():
    from reports.analytics import AnalyticsEngine
    account_id = _get_account_id()
    engine = AnalyticsEngine(account_id=account_id)
    stats = engine.summary_stats()
    if not stats:
        return jsonify({"error": "No data yet"}), 404
    stats["growth_7d"] = engine.growth_rate("follower_count", days=7)
    stats["growth_30d"] = engine.growth_rate("follower_count", days=30)
    stats["account_id"] = account_id
    return jsonify(stats)


@app.route("/api/growth")
def api_growth():
    days = request.args.get("days", 30, type=int)
    account_id = _get_account_id()
    from reports.analytics import AnalyticsEngine
    engine = AnalyticsEngine(account_id=account_id)
    df = engine.follower_growth(days=days)
    if df.empty:
        return jsonify([])
    data = [{"date": row["collected_at"].isoformat(), "followers": int(row["follower_count"])}
            for _, row in df.iterrows()]
    return jsonify(data)


@app.route("/api/likes-growth")
def api_likes_growth():
    days = request.args.get("days", 30, type=int)
    account_id = _get_account_id()
    from reports.analytics import AnalyticsEngine
    engine = AnalyticsEngine(account_id=account_id)
    df = engine.likes_growth(days=days)
    if df.empty:
        return jsonify([])
    data = [{"date": row["collected_at"].isoformat(), "likes": int(row["likes_count"])}
            for _, row in df.iterrows()]
    return jsonify(data)


@app.route("/api/top-videos")
def api_top_videos():
    limit = request.args.get("limit", 10, type=int)
    sort = request.args.get("sort", "views")
    account_id = _get_account_id()
    from reports.analytics import AnalyticsEngine
    engine = AnalyticsEngine(account_id=account_id)

    if sort == "engagement":
        df = engine.top_videos_by_engagement_rate(limit=limit)
    else:
        df = engine.top_videos_by_views(limit=limit)

    if df.empty:
        return jsonify([])
    videos = [{
        "title": str(row.get("title", ""))[:60] or "(no title)",
        "views": int(row["view_count"]),
        "likes": int(row["like_count"]),
        "comments": int(row["comment_count"]),
        "shares": int(row["share_count"]),
        "engagement_rate": round(row.get("engagement_rate", 0), 2),
    } for _, row in df.iterrows()]
    return jsonify(videos)


@app.route("/api/collection-history")
def api_collection_history():
    limit = request.args.get("limit", 10, type=int)
    account_id = _get_account_id()

    query = CollectionLog.select().order_by(CollectionLog.started_at.desc())
    if account_id:
        query = query.where(CollectionLog.account == account_id)
    logs = query.limit(limit)

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


# ── Comparison API ─────────────────────────────────────

@app.route("/api/compare")
def api_compare():
    """Compare summary stats across multiple accounts."""
    ids = request.args.get("ids", "")
    if not ids:
        return jsonify({"error": "Provide ?ids=1,2,3"}), 400
    account_ids = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    from reports.analytics import AnalyticsEngine
    return jsonify(AnalyticsEngine.compare_summary(account_ids))


@app.route("/api/compare/growth")
def api_compare_growth():
    """Compare follower growth across accounts."""
    ids = request.args.get("ids", "")
    days = request.args.get("days", 30, type=int)
    if not ids:
        return jsonify({"error": "Provide ?ids=1,2,3"}), 400
    account_ids = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    from reports.analytics import AnalyticsEngine
    return jsonify(AnalyticsEngine.compare_followers(account_ids, days=days))


@app.route("/api/compare/engagement")
def api_compare_engagement():
    """Compare engagement across accounts."""
    ids = request.args.get("ids", "")
    if not ids:
        return jsonify({"error": "Provide ?ids=1,2,3"}), 400
    account_ids = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    from reports.analytics import AnalyticsEngine
    return jsonify(AnalyticsEngine.compare_engagement(account_ids))


# ── Vercel Cron ────────────────────────────────────────

@app.route("/api/cron/collect")
def cron_collect():
    """Endpoint for Vercel Cron — collects all accounts."""
    auth_header = request.headers.get("Authorization")
    cron_secret = os.getenv("CRON_SECRET", "")
    if cron_secret and auth_header != f"Bearer {cron_secret}":
        return jsonify({"error": "Unauthorized"}), 401

    from collectors.scheduler import _async_collect_all
    asyncio.run(_async_collect_all())
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True, port=3000)
