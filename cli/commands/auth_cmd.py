import click
from rich.console import Console
from rich.panel import Panel

console = Console()


@click.group("auth")
def auth():
    """Manage TikTok authentication."""
    pass


@auth.command()
def login():
    """Authenticate with TikTok via OAuth2."""
    from config import settings

    if not settings.TIKTOK_CLIENT_KEY or settings.TIKTOK_CLIENT_KEY == "your_client_key_here":
        console.print("[red]Error:[/red] Set TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET in .env file")
        console.print("Register your app at: https://developers.tiktok.com/")
        raise SystemExit(1)

    from auth.oauth_server import OAuthCallbackServer
    from auth.token_manager import TokenManager

    console.print("Starting OAuth2 authorization flow...")
    console.print(f"Callback server will listen on port {settings.OAUTH_PORT}")

    server = OAuthCallbackServer()
    console.print("[blue]Opening browser for TikTok authorization...[/blue]")

    auth_code, error = server.start_and_wait()

    if error:
        console.print(f"[red]Authorization failed:[/red] {error}")
        raise SystemExit(1)

    console.print("Exchanging authorization code for tokens...")
    token_manager = TokenManager()
    tokens = token_manager.exchange_code(auth_code, server.code_verifier)

    console.print(Panel(
        f"[green]Successfully authenticated![/green]\n"
        f"Open ID: {tokens['open_id']}\n"
        f"Scopes: {tokens['scope']}",
        title="Authentication Complete",
    ))


@auth.command()
def status():
    """Show authentication status."""
    from auth.token_manager import TokenManager

    tm = TokenManager()
    info = tm.status()

    if not info:
        console.print("[yellow]Not authenticated.[/yellow] Run: tiktok-analytics auth login")
        return

    access_status = "[green]valid[/green]" if info["access_valid"] else "[red]expired[/red]"
    access_hours = info["access_expires_in"] // 3600
    refresh_days = info["refresh_expires_in"] // 86400

    console.print(Panel(
        f"Open ID: {info['open_id']}\n"
        f"Scopes: {info['scope']}\n"
        f"Access token: {access_status} ({access_hours}h remaining)\n"
        f"Refresh token: {refresh_days} days remaining",
        title="Auth Status",
    ))


@auth.command()
def refresh():
    """Force-refresh the access token."""
    from auth.token_manager import TokenManager

    tm = TokenManager()
    try:
        tm.refresh()
        console.print("[green]Token refreshed successfully.[/green]")
    except Exception as e:
        console.print(f"[red]Refresh failed:[/red] {e}")


@auth.command()
def logout():
    """Revoke tokens and log out."""
    from auth.token_manager import TokenManager

    tm = TokenManager()
    tm.revoke()
    console.print("[green]Logged out. Tokens revoked and deleted.[/green]")
