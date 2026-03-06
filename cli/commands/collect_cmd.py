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
@click.option("--account-id", default=None, type=int, help="Account ID (default: primary)")
@click.option("--all-accounts", is_flag=True, help="Collect for all accounts")
def collect_now(account_id, all_accounts):
    """Run immediate one-time data collection."""
    from db.database import init_db
    from auth.token_manager import TokenManager
    from tiktok_client.official_client import TikTokOfficialClient
    from collectors.profile_collector import ProfileCollector
    from collectors.video_collector import VideoCollector
    from db.models import Account, CollectionLog
    from datetime import datetime

    init_db()
    tm = TokenManager()

    if all_accounts:
        account_ids = tm.list_account_ids()
    elif account_id:
        account_ids = [account_id]
    else:
        primary = tm.get_primary_id()
        if not primary:
            console.print("[red]No accounts configured.[/red] Run: tiktok-analytics auth login")
            raise SystemExit(1)
        account_ids = [primary]

    async def _collect():
        for aid in account_ids:
            account = Account.get_or_none(Account.id == aid)
            if not account:
                console.print(f"[red]Account {aid} not found.[/red]")
                continue

            atm = TokenManager(account_id=aid)
            if not atm.load(aid):
                console.print(f"[red]No tokens for account {aid}.[/red]")
                continue

            official = TikTokOfficialClient(atm)
            profile_collector = ProfileCollector(account, official)
            video_collector = VideoCollector(account, official)

            log = CollectionLog.create(account=account, started_at=datetime.utcnow(), status="running")

            try:
                with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
                    task = progress.add_task(f"[{account.display_name or aid}] Collecting...", total=None)
                    profile = await profile_collector.collect()
                    progress.update(task, description=f"[{account.display_name}] Videos...")
                    new_videos, snapshots = await video_collector.collect()

                log.status = "success"
                log.videos_collected = snapshots
                log.completed_at = datetime.utcnow()
                log.save()

                console.print(f"[green]{profile.display_name}:[/green] {profile.follower_count:,} followers, {new_videos} new videos, {snapshots} snapshots")

            except Exception as e:
                log.status = "failed"
                log.error_message = str(e)
                log.completed_at = datetime.utcnow()
                log.save()
                console.print(f"[red]Account {aid} failed:[/red] {e}")

            finally:
                await official.close()

    asyncio.run(_collect())


@collect.command("schedule")
@click.option("--interval", default=None, type=int, help="Collection interval in hours")
def collect_schedule(interval):
    """Start periodic data collection for all accounts."""
    from collectors.scheduler import CollectionScheduler

    scheduler = CollectionScheduler(interval_hours=interval)
    console.print(f"[blue]Starting scheduler (every {scheduler.interval_hours}h) for all accounts...[/blue]")
    console.print("Press Ctrl+C to stop.")
    scheduler.start()


@collect.command("history")
@click.option("--limit", default=10, help="Number of entries to show")
def collect_history(limit):
    """Show collection history."""
    from db.database import init_db
    from db.models import CollectionLog, Account
    init_db()

    logs = (CollectionLog
            .select(CollectionLog, Account)
            .join(Account, on=(CollectionLog.account == Account.id), join_type="LEFT")
            .order_by(CollectionLog.started_at.desc())
            .limit(limit))

    if not logs:
        console.print("[yellow]No collection history found.[/yellow]")
        return

    from rich.table import Table
    table = Table(title="Collection History")
    table.add_column("Date", style="cyan")
    table.add_column("Account")
    table.add_column("Status")
    table.add_column("Videos", justify="right")
    table.add_column("Duration")

    for log in logs:
        status_style = {"success": "green", "failed": "red", "partial": "yellow", "running": "blue"}
        status = f"[{status_style.get(log.status, 'white')}]{log.status}[/]"
        duration = ""
        if log.completed_at and log.started_at:
            delta = log.completed_at - log.started_at
            duration = f"{delta.total_seconds():.1f}s"
        account_name = log.account.display_name if log.account else "-"
        table.add_row(str(log.started_at)[:19], account_name, status, str(log.videos_collected), duration)

    console.print(table)
