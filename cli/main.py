import click
import logging

from cli.commands.auth_cmd import auth
from cli.commands.collect_cmd import collect
from cli.commands.report_cmd import report


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def cli(verbose):
    """TikTok Analytics — monitor multiple accounts and track growth."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


@cli.command()
def status():
    """Show status of all connected accounts."""
    from rich.console import Console
    from rich.panel import Panel
    from db.database import init_db
    from db.models import Account, ProfileSnapshot, VideoMetricsSnapshot, CollectionLog

    console = Console()
    init_db()

    accounts = Account.select()
    if not accounts:
        console.print("[yellow]No accounts connected.[/yellow] Run: tiktok-analytics auth login")
        return

    for account in accounts:
        latest = (ProfileSnapshot
                  .select()
                  .where(ProfileSnapshot.account == account.id)
                  .order_by(ProfileSnapshot.collected_at.desc())
                  .first())

        if not latest:
            console.print(Panel(
                f"[yellow]No data collected yet.[/yellow]\nRun: tiktok-analytics collect now --account-id {account.id}",
                title=f"{account.display_name or 'Unknown'} (@{account.username or '-'})",
            ))
            continue

        total_snapshots = ProfileSnapshot.select().where(ProfileSnapshot.account == account.id).count()
        total_metrics = VideoMetricsSnapshot.select().where(VideoMetricsSnapshot.account == account.id).count()

        last_log = (CollectionLog
                    .select()
                    .where(CollectionLog.account == account.id)
                    .order_by(CollectionLog.started_at.desc())
                    .first())
        last_collection = str(last_log.started_at)[:19] if last_log else "never"

        primary = " [cyan](primary)[/cyan]" if account.is_primary else ""

        console.print(Panel(
            f"Followers:   {latest.follower_count:>10,}\n"
            f"Following:   {latest.following_count:>10,}\n"
            f"Total Likes: {latest.likes_count:>10,}\n"
            f"Videos:      {latest.video_count:>10,}\n"
            f"\n"
            f"Last collection: {last_collection}\n"
            f"Data: {total_snapshots} profile snapshots, {total_metrics} video metric snapshots",
            title=f"{latest.display_name} (@{latest.username}){primary}",
        ))


cli.add_command(auth)
cli.add_command(collect)
cli.add_command(report)


if __name__ == "__main__":
    cli()
