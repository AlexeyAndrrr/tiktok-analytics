import asyncio

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
@click.option("--headless/--no-headless", default=False,
              help="Run browser in headless mode (use --no-headless for CAPTCHA)")
def login(headless):
    """Add a TikTok account by logging in with credentials."""
    from auth.browser_login import BrowserLogin, CaptchaRequired, TwoFactorRequired, InvalidCredentials
    from auth.token_manager import TokenManager
    from db.database import init_db
    init_db()

    login_id = click.prompt("TikTok email, phone, or username")
    password = click.prompt("Password", hide_input=True)

    console.print("\n[blue]Opening browser for TikTok login...[/blue]")
    if not headless:
        console.print("[dim]A browser window will open. Complete any CAPTCHA if prompted.[/dim]")
    else:
        console.print("[dim]Running in headless mode. Use --no-headless if CAPTCHA appears.[/dim]")

    bl = BrowserLogin()
    try:
        cookies = asyncio.run(bl.login(login_id, password, headless=headless))
    except CaptchaRequired:
        console.print("\n[yellow]CAPTCHA detected.[/yellow] Re-run with [bold]--no-headless[/bold] to solve it manually:")
        console.print("  [dim]python -m cli.main auth login --no-headless[/dim]")
        raise SystemExit(1)
    except TwoFactorRequired:
        console.print("\n[yellow]2FA verification required.[/yellow] Re-run with [bold]--no-headless[/bold]:")
        console.print("  [dim]python -m cli.main auth login --no-headless[/dim]")
        raise SystemExit(1)
    except InvalidCredentials as e:
        console.print(f"\n[red]Login failed:[/red] {e}")
        raise SystemExit(1)
    except Exception as e:
        console.print(f"\n[red]Login error:[/red] {e}")
        raise SystemExit(1)

    tm = TokenManager()
    session_data = tm.store_session(login_id, cookies)

    console.print(Panel(
        f"[green]Account added![/green]\n"
        f"Account ID: {session_data['account_id']}\n"
        f"Login: {login_id}",
        title="Login Complete",
    ))


@auth.command("list")
def list_accounts():
    """List all connected accounts."""
    from db.database import init_db
    from db.models import Account
    init_db()

    accounts = Account.select()
    if not accounts:
        console.print("[yellow]No accounts connected.[/yellow] Run: python -m cli.main auth login")
        return

    table = Table(title="Connected Accounts")
    table.add_column("ID", justify="right")
    table.add_column("Name")
    table.add_column("Username")
    table.add_column("Login")
    table.add_column("Primary")

    for a in accounts:
        primary = "[green]yes[/green]" if a.is_primary else ""
        table.add_row(
            str(a.id),
            a.display_name,
            f"@{a.username or '-'}",
            a.login_id or "-",
            primary,
        )

    console.print(table)


@auth.command()
def status():
    """Show session status for all accounts."""
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

        session_status = "[green]valid[/green]" if info["session_valid"] else "[red]expired[/red]"
        primary = " [cyan](primary)[/cyan]" if account and account.is_primary else ""

        console.print(Panel(
            f"Session: {session_status}\n"
            f"Login: {info.get('login_id', '-')}\n"
            f"Stored: {info['stored_hours_ago']}h ago\n"
            f"Cookies: {info['cookies_count']}",
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
    """Remove an account and its session data."""
    from auth.token_manager import TokenManager
    from db.database import init_db
    init_db()

    tm = TokenManager()
    tm.revoke(account_id)
    console.print(f"[green]Account {account_id} removed.[/green]")
