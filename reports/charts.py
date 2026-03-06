import plotly.graph_objects as go
import plotly.express as px
import pandas as pd


class ChartGenerator:
    """Generates interactive Plotly charts from analytics DataFrames."""

    COLORS = {
        "primary": "#fe2c55",    # TikTok red/pink
        "secondary": "#25f4ee",  # TikTok cyan
        "dark": "#161823",
        "text": "#ffffff",
    }

    def _base_layout(self, title: str) -> dict:
        return dict(
            title=title,
            template="plotly_dark",
            paper_bgcolor=self.COLORS["dark"],
            plot_bgcolor=self.COLORS["dark"],
            font=dict(color=self.COLORS["text"]),
        )

    def follower_growth_chart(self, df: pd.DataFrame) -> go.Figure:
        """Line chart: followers over time."""
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df["collected_at"],
            y=df["follower_count"],
            mode="lines+markers",
            name="Followers",
            line=dict(color=self.COLORS["primary"], width=2),
            marker=dict(size=4),
        ))
        fig.update_layout(**self._base_layout("Follower Growth"))
        fig.update_xaxes(title="Date")
        fig.update_yaxes(title="Followers")
        return fig

    def likes_growth_chart(self, df: pd.DataFrame) -> go.Figure:
        """Line chart: total likes over time."""
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df["collected_at"],
            y=df["likes_count"],
            mode="lines+markers",
            name="Total Likes",
            line=dict(color=self.COLORS["secondary"], width=2),
            marker=dict(size=4),
        ))
        fig.update_layout(**self._base_layout("Total Likes Growth"))
        fig.update_xaxes(title="Date")
        fig.update_yaxes(title="Likes")
        return fig

    def top_videos_bar_chart(self, df: pd.DataFrame) -> go.Figure:
        """Horizontal bar chart of top videos by views."""
        df = df.sort_values("view_count", ascending=True)
        labels = df["title"].apply(lambda x: (str(x)[:30] + "...") if len(str(x)) > 30 else str(x))

        fig = go.Figure()
        fig.add_trace(go.Bar(
            y=labels,
            x=df["view_count"],
            orientation="h",
            marker_color=self.COLORS["primary"],
            name="Views",
        ))
        fig.update_layout(**self._base_layout("Top Videos by Views"))
        fig.update_xaxes(title="Views")
        return fig

    def engagement_dashboard(self, df: pd.DataFrame) -> go.Figure:
        """Multi-line chart: likes, comments, shares over time."""
        fig = go.Figure()

        for col, color, name in [
            ("like_count", self.COLORS["primary"], "Likes"),
            ("comment_count", self.COLORS["secondary"], "Comments"),
            ("share_count", "#ffc107", "Shares"),
        ]:
            if col in df.columns:
                fig.add_trace(go.Scatter(
                    x=df["collected_at"],
                    y=df[col],
                    mode="lines",
                    name=name,
                    line=dict(color=color, width=2),
                ))

        fig.update_layout(**self._base_layout("Engagement Over Time"))
        return fig

    def posting_heatmap(self, df: pd.DataFrame) -> go.Figure:
        """Heatmap: day of week vs hour of day for posting."""
        if df.empty or "hour" not in df.columns:
            return go.Figure()

        days_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        pivot = df.pivot_table(index="day_of_week", columns="hour", values="avg_engagement", fill_value=0)

        # Reindex to proper day order
        pivot = pivot.reindex(days_order)

        fig = go.Figure(data=go.Heatmap(
            z=pivot.values,
            x=pivot.columns,
            y=pivot.index,
            colorscale=[[0, self.COLORS["dark"]], [1, self.COLORS["primary"]]],
        ))
        fig.update_layout(**self._base_layout("Best Posting Times (by Engagement)"))
        fig.update_xaxes(title="Hour of Day")
        fig.update_yaxes(title="Day of Week")
        return fig

    def engagement_rate_distribution(self, df: pd.DataFrame) -> go.Figure:
        """Histogram of engagement rates across videos."""
        if "engagement_rate" not in df.columns:
            return go.Figure()

        fig = go.Figure(data=go.Histogram(
            x=df["engagement_rate"],
            nbinsx=20,
            marker_color=self.COLORS["primary"],
        ))
        fig.update_layout(**self._base_layout("Engagement Rate Distribution"))
        fig.update_xaxes(title="Engagement Rate (%)")
        fig.update_yaxes(title="Number of Videos")
        return fig

    def video_lifecycle_chart(self, df: pd.DataFrame) -> go.Figure:
        """Line chart: how a video's views grow over time."""
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df["collected_at"],
            y=df["view_count"],
            mode="lines+markers",
            name="Views",
            line=dict(color=self.COLORS["primary"], width=2),
        ))
        fig.add_trace(go.Scatter(
            x=df["collected_at"],
            y=df["like_count"],
            mode="lines+markers",
            name="Likes",
            line=dict(color=self.COLORS["secondary"], width=2),
        ))
        fig.update_layout(**self._base_layout("Video Performance Over Time"))
        return fig
