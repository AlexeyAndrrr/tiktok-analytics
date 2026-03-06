import os
from pathlib import Path

from reports.analytics import AnalyticsEngine
from reports.charts import ChartGenerator


class ReportExporter:
    """Export analytics as HTML reports or CSV data."""

    def __init__(self, engine: AnalyticsEngine):
        self.engine = engine
        self.charts = ChartGenerator()

    def export_html(self, output_path: str):
        """Generate a comprehensive HTML report with embedded charts."""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        stats = self.engine.summary_stats()
        if not stats:
            raise ValueError("No data to export. Collect some data first.")

        # Generate charts as HTML divs
        chart_divs = []

        df_followers = self.engine.follower_growth(days=30)
        if not df_followers.empty:
            fig = self.charts.follower_growth_chart(df_followers)
            chart_divs.append(fig.to_html(full_html=False, include_plotlyjs=False))

        df_likes = self.engine.likes_growth(days=30)
        if not df_likes.empty:
            fig = self.charts.likes_growth_chart(df_likes)
            chart_divs.append(fig.to_html(full_html=False, include_plotlyjs=False))

        df_top = self.engine.top_videos_by_views(limit=10)
        if not df_top.empty:
            fig = self.charts.top_videos_bar_chart(df_top)
            chart_divs.append(fig.to_html(full_html=False, include_plotlyjs=False))

        df_eng = self.engine.top_videos_by_engagement_rate(limit=50)
        if not df_eng.empty:
            fig = self.charts.engagement_rate_distribution(df_eng)
            chart_divs.append(fig.to_html(full_html=False, include_plotlyjs=False))

        df_times = self.engine.best_posting_times()
        if not df_times.empty:
            fig = self.charts.posting_heatmap(df_times)
            chart_divs.append(fig.to_html(full_html=False, include_plotlyjs=False))

        charts_html = "\n<hr>\n".join(chart_divs) if chart_divs else "<p>Not enough data for charts yet.</p>"

        growth_7d = self.engine.growth_rate("follower_count", days=7)
        growth_30d = self.engine.growth_rate("follower_count", days=30)

        def fmt_g(val):
            if val is None:
                return "n/a"
            return f"{'+' if val >= 0 else ''}{val:.1f}%"

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TikTok Analytics Report</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: #161823;
            color: #fff;
            margin: 0;
            padding: 20px;
        }}
        .header {{
            text-align: center;
            padding: 30px 0;
            border-bottom: 2px solid #fe2c55;
            margin-bottom: 30px;
        }}
        .header h1 {{
            color: #fe2c55;
            margin: 0;
            font-size: 2.5em;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin: 30px 0;
        }}
        .stat-card {{
            background: #1e1e2e;
            border-radius: 12px;
            padding: 20px;
            text-align: center;
        }}
        .stat-value {{
            font-size: 2em;
            font-weight: bold;
            color: #fe2c55;
        }}
        .stat-label {{
            color: #888;
            margin-top: 5px;
        }}
        .stat-change {{
            color: #25f4ee;
            font-size: 0.9em;
        }}
        .charts-section {{
            margin-top: 40px;
        }}
        hr {{
            border: none;
            border-top: 1px solid #333;
            margin: 30px 0;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>TikTok Analytics</h1>
        <p>{stats['display_name']} (@{stats['username']})</p>
    </div>

    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-value">{stats['follower_count']:,}</div>
            <div class="stat-label">Followers</div>
            <div class="stat-change">7d: {fmt_g(growth_7d)} | 30d: {fmt_g(growth_30d)}</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{stats['likes_count']:,}</div>
            <div class="stat-label">Total Likes</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{stats['video_count']}</div>
            <div class="stat-label">Videos</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{stats['avg_views']:,.0f}</div>
            <div class="stat-label">Avg Views/Video</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{stats['avg_engagement_rate']:.1f}%</div>
            <div class="stat-label">Avg Engagement Rate</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{stats['best_video_views']:,}</div>
            <div class="stat-label">Best Video Views</div>
        </div>
    </div>

    <div class="charts-section">
        {charts_html}
    </div>
</body>
</html>"""

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

    def export_csv(self, output_path: str):
        """Export video metrics as CSV."""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        df = self.engine.top_videos_by_views(limit=10000)
        if df.empty:
            raise ValueError("No data to export.")
        df.to_csv(output_path, index=False)
