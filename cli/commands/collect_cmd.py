import asyncio
import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


@click.group("collect")
def collect():
    """Collect data from TikTok."""
    pass


@collect.command("now")
def collect_now():
    """Run immediate one-time data collection."""
    from db.database import init_db
    from auth.token_manager import TokenManager
    from tiktok_client.official_client import TikTokOfficialClient
    from tiktok_client.unofficial_client import TikTokUnofficialClient
    from collectors.profile_collector import ProfileCollector
    from collectors.video_collector import VideoCollector
    from db.models import CollectionLog
    from config import settings
    from datetime import datetime

    init_db()

    tm = TokenManager()
    if not tm.load():
        console.print("[red]Not authenticated.[/red] Run: tiktok-analytics auth login")
        raise SystemExit(1)

    async def _collect():
        official = TikTokOfficialClient(tm)
        unofficial = TikTokUnofficialClient(settings.TIKTOK_USERNAME) if settings.TIKTOK_USERNAME else None

        profile_collector = ProfileCollector(official, unofficial)
        video_collector = VideoCollector(official, unofficial)

        log = CollectionLog.create(started_at=datetime.utcnow(), status="running")

        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task("Collecting profile data...", total=None)
                profile = await profile_collector.collect()
                progress.update(task, description="Profile collected.")

                progress.update(task, description="Collecting videos and metrics...")
                new_videos, snapshots = await video_collector.collect()
                progress.update(task, description="Done!")

            log.status = "success"
            log.videos_collected = snapshots
            log.completed_at = datetime.utcnow()
            log.save()

            console.print()
            console.print(f"[green]Collection complete![/green]")
            console.print(f"  Profile: {profile.display_name} (@{profile.username})")
            console.print(f"  Followers: {profile.follower_count:,}")
            console.print(f"  Total likes: {profile.likes_count:,}")
            console.print(f"  Videos: {profile.video_count}")
            console.print(f"  New videos found: {new_videos}")
            console.print(f"  Metric snapshots: {snapshots}")

        except Exception as e:
            log.status = "failed"
            log.error_message = str(e)
            log.completed_at = datetime.utcnow()
            log.save()
            console.print(f"[red]Collection failed:[/red] {e}")

        finally:
            await official.close()
            if unofficial:
                await unofficial.close()

    asyncio.run(_collect())


@collect.command("schedule")
@click.option("--interval", default=None, type=int, help="Collection interval in hours (default: from .env)")
def collect_schedule(interval):
    """Start periodic data collection."""
    from collectors.scheduler import CollectionScheduler

    scheduler = CollectionScheduler(interval_hours=interval)
    console.print(f"[blue]Starting scheduler (every {scheduler.interval_hours}h)...[/blue]")
    console.print("Press Ctrl+C to stop.")
    scheduler.start()


@collect.command("history")
@click.option("--limit", default=10, help="Number of entries to show")
def collect_history(limit):
    """Show collection history."""
    from db.database import init_db
    from db.models import CollectionLog

    init_db()

    logs = (CollectionLog
            .select()
            .order_by(CollectionLog.started_at.desc())
            .limit(limit))

    if not logs:
        console.print("[yellow]No collection history found.[/yellow]")
        return

    from rich.table import Table
    table = Table(title="Collection History")
    table.add_column("Date", style="cyan")
    table.add_column("Status")
    table.add_column("Videos", justify="right")
    table.add_column("Duration")
    table.add_column("Error")

    for log in logs:
        status_style = {"success": "green", "failed": "red", "partial": "yellow", "running": "blue"}
        status = f"[{status_style.get(log.status, 'white')}]{log.status}[/]"

        duration = ""
        if log.completed_at and log.started_at:
            delta = log.completed_at - log.started_at
            duration = f"{delta.total_seconds():.1f}s"

        table.add_row(
            str(log.started_at)[:19],
            status,
            str(log.videos_collected),
            duration,
            (log.error_message or "")[:50],
        )

    console.print(table)
