import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


@click.group("report")
def report():
    """Generate analytics reports."""
    pass


@report.command()
def summary():
    """Show a text summary of account analytics."""
    from db.database import init_db
    from reports.analytics import AnalyticsEngine

    init_db()
    engine = AnalyticsEngine()
    stats = engine.summary_stats()

    if not stats:
        console.print("[yellow]No data yet.[/yellow] Run: tiktok-analytics collect now")
        return

    growth_7d = engine.growth_rate("follower_count", days=7)
    growth_30d = engine.growth_rate("follower_count", days=30)

    def fmt_growth(val):
        if val is None:
            return "n/a"
        sign = "+" if val >= 0 else ""
        return f"{sign}{val:.1f}%"

    console.print(Panel(
        f"[bold]{stats['display_name']}[/bold] (@{stats['username']})\n"
        f"\n"
        f"Followers:  {stats['follower_count']:>10,}  (7d: {fmt_growth(growth_7d)}, 30d: {fmt_growth(growth_30d)})\n"
        f"Following:  {stats['following_count']:>10,}\n"
        f"Total Likes:{stats['likes_count']:>10,}\n"
        f"Videos:     {stats['video_count']:>10,}\n"
        f"\n"
        f"Avg views/video:      {stats['avg_views']:>10,.0f}\n"
        f"Avg engagement rate:  {stats['avg_engagement_rate']:>9.1f}%\n"
        f"Best video views:     {stats['best_video_views']:>10,}\n"
        f"\n"
        f"Data points: {stats['total_snapshots']} profile snapshots, "
        f"{stats['total_metric_snapshots']} video metric snapshots",
        title="TikTok Account Summary",
    ))


@report.command()
@click.option("--days", default=30, help="Number of days to show")
def growth(days):
    """Generate follower and likes growth charts."""
    from db.database import init_db
    from reports.analytics import AnalyticsEngine
    from reports.charts import ChartGenerator

    init_db()
    engine = AnalyticsEngine()
    charts = ChartGenerator()

    df = engine.follower_growth(days=days)
    if df.empty:
        console.print("[yellow]Not enough data for growth chart.[/yellow] Collect data over multiple days.")
        return

    fig = charts.follower_growth_chart(df)
    output_path = "data/reports/follower_growth.html"
    fig.write_html(output_path)
    console.print(f"[green]Follower growth chart saved to:[/green] {output_path}")

    df_likes = engine.likes_growth(days=days)
    if not df_likes.empty:
        fig2 = charts.likes_growth_chart(df_likes)
        output_path2 = "data/reports/likes_growth.html"
        fig2.write_html(output_path2)
        console.print(f"[green]Likes growth chart saved to:[/green] {output_path2}")


@report.command()
@click.option("--top", default=10, help="Number of top videos to show")
@click.option("--sort", type=click.Choice(["views", "likes", "engagement"]), default="views")
def videos(top, sort):
    """Show top performing videos."""
    from db.database import init_db
    from reports.analytics import AnalyticsEngine

    init_db()
    engine = AnalyticsEngine()

    if sort == "engagement":
        df = engine.top_videos_by_engagement_rate(limit=top)
    else:
        df = engine.top_videos_by_views(limit=top)

    if df.empty:
        console.print("[yellow]No video data available.[/yellow]")
        return

    table = Table(title=f"Top {top} Videos by {sort.title()}")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Title", max_width=40)
    table.add_column("Views", justify="right")
    table.add_column("Likes", justify="right")
    table.add_column("Comments", justify="right")
    table.add_column("Shares", justify="right")
    table.add_column("Eng.Rate", justify="right")

    for i, row in df.iterrows():
        title = str(row.get("title", ""))[:40] or "(no title)"
        views = f"{row['view_count']:,}"
        likes = f"{row['like_count']:,}"
        comments = f"{row['comment_count']:,}"
        shares = f"{row['share_count']:,}"
        eng = f"{row.get('engagement_rate', 0):.1f}%"

        table.add_row(str(i + 1), title, views, likes, comments, shares, eng)

    console.print(table)


@report.command("export")
@click.option("--format", "fmt", type=click.Choice(["html", "csv"]), default="html")
@click.option("--output", "-o", default=None, help="Output file path")
def export_report(fmt, output):
    """Export analytics report."""
    from db.database import init_db
    from reports.analytics import AnalyticsEngine
    from reports.export import ReportExporter

    init_db()
    engine = AnalyticsEngine()
    exporter = ReportExporter(engine)

    if fmt == "html":
        path = output or "data/reports/report.html"
        exporter.export_html(path)
        console.print(f"[green]HTML report saved to:[/green] {path}")
    else:
        path = output or "data/reports/data.csv"
        exporter.export_csv(path)
        console.print(f"[green]CSV export saved to:[/green] {path}")
