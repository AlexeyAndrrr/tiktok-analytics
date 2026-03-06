import click
import logging

from cli.commands.auth_cmd import auth
from cli.commands.collect_cmd import collect
from cli.commands.report_cmd import report


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def cli(verbose):
    """TikTok Analytics — monitor your account and track growth."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


@cli.command()
def status():
    """Show current account status and last collection."""
    from rich.console import Console
    from rich.panel import Panel
    from db.database import init_db
    from db.models import ProfileSnapshot, VideoMetricsSnapshot, CollectionLog
    from auth.token_manager import TokenManager

    console = Console()
    init_db()

    # Auth status
    tm = TokenManager()
    auth_info = tm.status()
    if not auth_info:
        console.print("[yellow]Not authenticated.[/yellow] Run: tiktok-analytics auth login")
        return

    # Latest profile
    latest = (ProfileSnapshot
              .select()
              .order_by(ProfileSnapshot.collected_at.desc())
              .first())

    if not latest:
        console.print("[yellow]No data collected yet.[/yellow] Run: tiktok-analytics collect now")
        return

    # Counts
    total_snapshots = ProfileSnapshot.select().count()
    total_metrics = VideoMetricsSnapshot.select().count()

    # Last collection
    last_log = (CollectionLog
                .select()
                .order_by(CollectionLog.started_at.desc())
                .first())
    last_collection = str(last_log.started_at)[:19] if last_log else "never"

    console.print(Panel(
        f"[bold]{latest.display_name}[/bold] (@{latest.username})\n"
        f"Verified: {'yes' if latest.is_verified else 'no'}\n"
        f"\n"
        f"Followers:   {latest.follower_count:>10,}\n"
        f"Following:   {latest.following_count:>10,}\n"
        f"Total Likes: {latest.likes_count:>10,}\n"
        f"Videos:      {latest.video_count:>10,}\n"
        f"\n"
        f"Last collection: {last_collection}\n"
        f"Database: {total_snapshots} profile snapshots, {total_metrics} video metric snapshots",
        title="Account Status",
    ))


cli.add_command(auth)
cli.add_command(collect)
cli.add_command(report)


if __name__ == "__main__":
    cli()
