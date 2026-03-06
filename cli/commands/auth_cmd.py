import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


@click.group("auth")
def auth():
    """Manage TikTok authentication and accounts."""
    pass


@auth.command()
def login():
    """Add a new TikTok account via OAuth2."""
    from config import settings

    if not settings.TIKTOK_CLIENT_KEY or settings.TIKTOK_CLIENT_KEY == "your_client_key_here":
        console.print("[red]Error:[/red] Set TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET in .env file")
        raise SystemExit(1)

    from auth.oauth_server import OAuthCallbackServer
    from auth.token_manager import TokenManager
    from db.database import init_db
    init_db()

    server = OAuthCallbackServer()
    console.print("[blue]Opening browser for TikTok authorization...[/blue]")

    auth_code, error = server.start_and_wait()
    if error:
        console.print(f"[red]Authorization failed:[/red] {error}")
        raise SystemExit(1)

    tm = TokenManager()
    tokens = tm.exchange_code(auth_code, server.code_verifier)

    console.print(Panel(
        f"[green]Account added![/green]\n"
        f"Account ID: {tokens.get('account_id')}\n"
        f"Open ID: {tokens['open_id']}\n"
        f"Scopes: {tokens['scope']}",
        title="Authentication Complete",
    ))


@auth.command("list")
def list_accounts():
    """List all connected accounts."""
    from db.database import init_db
    from db.models import Account
    init_db()

    accounts = Account.select()
    if not accounts:
        console.print("[yellow]No accounts connected.[/yellow] Run: tiktok-analytics auth login")
        return

    table = Table(title="Connected Accounts")
    table.add_column("ID", justify="right")
    table.add_column("Name")
    table.add_column("Username")
    table.add_column("Primary")

    for a in accounts:
        primary = "[green]yes[/green]" if a.is_primary else ""
        table.add_row(str(a.id), a.display_name, f"@{a.username or '-'}", primary)

    console.print(table)


@auth.command()
def status():
    """Show authentication status for all accounts."""
    from auth.token_manager import TokenManager
    from db.database import init_db
    from db.models import Account
    init_db()

    tm = TokenManager()
    account_ids = tm.list_account_ids()

    if not account_ids:
        console.print("[yellow]No accounts connected.[/yellow]")
        return

    for aid in account_ids:
        info = tm.status(aid)
        account = Account.get_or_none(Account.id == aid)
        name = account.display_name if account else f"Account {aid}"

        access_status = "[green]valid[/green]" if info["access_valid"] else "[red]expired[/red]"
        access_hours = info["access_expires_in"] // 3600
        refresh_days = info["refresh_expires_in"] // 86400
        primary = " [cyan](primary)[/cyan]" if account and account.is_primary else ""

        console.print(Panel(
            f"Access token: {access_status} ({access_hours}h remaining)\n"
            f"Refresh token: {refresh_days} days remaining",
            title=f"{name}{primary}",
        ))


@auth.command("set-primary")
@click.argument("account_id", type=int)
def set_primary(account_id):
    """Set an account as the primary account."""
    from auth.token_manager import TokenManager
    from db.database import init_db
    init_db()

    tm = TokenManager()
    tm.set_primary(account_id)
    console.print(f"[green]Account {account_id} set as primary.[/green]")


@auth.command()
@click.argument("account_id", type=int)
def remove(account_id):
    """Remove an account and its tokens."""
    from auth.token_manager import TokenManager
    from db.database import init_db
    init_db()

    tm = TokenManager()
    tm.revoke(account_id)
    console.print(f"[green]Account {account_id} removed.[/green]")
