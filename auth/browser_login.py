"""Automated TikTok login via Playwright browser automation."""

import asyncio
import random
import logging
import traceback

from config import settings

logger = logging.getLogger(__name__)


class LoginError(Exception):
    """Base error for login failures."""
    pass


class InvalidCredentials(LoginError):
    """Wrong username/password."""
    pass


class CaptchaRequired(LoginError):
    """CAPTCHA detected — user must solve manually."""
    pass


class TwoFactorRequired(LoginError):
    """Two-factor authentication step detected."""
    pass


def run_login_sync(login_id: str, password: str, headless: bool = False, timeout: int = 120) -> dict:
    """
    Synchronous wrapper that safely runs the async login.
    Works correctly inside Flask routes (avoids asyncio.run() conflicts).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    bl = BrowserLogin()

    if loop and loop.is_running():
        # We're inside an existing event loop (e.g. Flask with async)
        # Run in a new thread to avoid conflicts
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(
                asyncio.run,
                bl.login(login_id, password, headless=headless, timeout=timeout)
            )
            return future.result(timeout=timeout + 30)
    else:
        return asyncio.run(bl.login(login_id, password, headless=headless, timeout=timeout))


class BrowserLogin:
    """Automates TikTok login via Playwright and captures session cookies."""

    LOGIN_URL = "https://www.tiktok.com/login/phone-email/email"
    LOGIN_URL_ALT = "https://www.tiktok.com/login"
    HOME_URL = "https://www.tiktok.com"

    # Cookies that indicate successful login
    SESSION_COOKIES = {"sessionid", "sid_tt", "uid_tt", "sid_guard"}

    async def login(
        self,
        login_id: str,
        password: str,
        headless: bool | None = None,
        timeout: int | None = None,
    ) -> dict:
        """
        Log into TikTok and return session cookies.

        Args:
            login_id: Email, phone, or username.
            password: Account password.
            headless: Run without GUI (None = use config setting).
            timeout: Max seconds to wait for login.

        Returns:
            Dict of {cookie_name: cookie_value, ...}

        Raises:
            InvalidCredentials: Wrong login/password.
            CaptchaRequired: CAPTCHA detected.
            TwoFactorRequired: 2FA step detected.
            LoginError: Generic login failure.
        """
        from playwright.async_api import async_playwright

        if headless is None:
            headless = settings.BROWSER_HEADLESS
        if timeout is None:
            timeout = settings.BROWSER_LOGIN_TIMEOUT

        profile_dir = str(settings.BROWSER_PROFILES_DIR / self._safe_name(login_id))

        logger.info(f"Starting login for '{login_id}' (headless={headless}, timeout={timeout}s)")

        async with async_playwright() as pw:
            # Use newer Chrome user agent
            ua = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            )

            try:
                browser = await pw.chromium.launch_persistent_context(
                    user_data_dir=profile_dir,
                    headless=headless,
                    viewport={"width": 1280, "height": 720},
                    user_agent=ua,
                    locale="en-US",
                    ignore_https_errors=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                    ],
                )
            except Exception as e:
                logger.error(f"Failed to launch browser: {e}")
                raise LoginError(
                    f"Cannot launch browser: {e}. "
                    "Make sure Playwright is installed: python -m playwright install chromium"
                )

            try:
                page = browser.pages[0] if browser.pages else await browser.new_page()

                # Mask automation flags
                await page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                    window.chrome = { runtime: {} };
                """)

                # Navigate to login page
                logger.info("Navigating to TikTok login page...")
                try:
                    await page.goto(self.LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
                except Exception:
                    logger.warning("Primary login URL failed, trying alternative...")
                    await page.goto(self.LOGIN_URL_ALT, wait_until="domcontentloaded", timeout=30000)

                await self._random_delay(2.0, 4.0)

                # Check if already logged in (cookies from persistent context)
                if await self._has_session(browser):
                    logger.info("Already logged in from previous session.")
                    return self._extract_cookies(await browser.cookies("https://www.tiktok.com"))

                # Take screenshot for debugging
                logger.info(f"Current URL: {page.url}")
                logger.info("Looking for login form...")

                # If we're on the general login page, click email/phone tab
                await self._navigate_to_email_login(page)

                # Find and fill login form
                await self._fill_credentials(page, login_id, password)

                # Click login button
                await self._click_login(page)

                # Wait for result
                cookies = await self._wait_for_login(browser, page, timeout)
                return cookies

            except (LoginError, InvalidCredentials, CaptchaRequired, TwoFactorRequired):
                raise
            except Exception as e:
                logger.error(f"Unexpected error during login: {traceback.format_exc()}")
                raise LoginError(f"Login failed: {e}")
            finally:
                await browser.close()

    async def _navigate_to_email_login(self, page):
        """If on general login page, navigate to email/password login."""
        await self._random_delay(1.0, 2.0)

        # Try clicking "Use phone / email / username" link if present
        email_link = (
            await page.query_selector('a[href*="phone-email"]')
            or await page.query_selector('div[class*="channel-item"]:has-text("phone")')
            or await page.query_selector('text=phone / email / username')
            or await page.query_selector('text=Use phone')
            or await page.query_selector('[data-e2e="channel-item"]')
        )
        if email_link:
            logger.info("Clicking email/phone login option...")
            await email_link.click()
            await self._random_delay(1.0, 2.0)

        # Try clicking "Log in with email" tab if present
        email_tab = (
            await page.query_selector('a[href*="email"]')
            or await page.query_selector('text=Log in with email')
            or await page.query_selector('text=Email / Username')
            or await page.query_selector('[data-e2e="login-email-tab"]')
        )
        if email_tab:
            logger.info("Clicking email tab...")
            await email_tab.click()
            await self._random_delay(1.0, 2.0)

    async def _fill_credentials(self, page, login_id: str, password: str):
        """Fill in the login form fields with human-like delays."""
        # Wait for any input to appear
        selectors = [
            'input[name="username"]',
            'input[placeholder*="email" i]',
            'input[placeholder*="Email" i]',
            'input[placeholder*="phone" i]',
            'input[placeholder*="Phone" i]',
            'input[placeholder*="Username" i]',
            'input[type="text"]',
            'input[type="tel"]',
        ]

        login_input = None
        for sel in selectors:
            try:
                await page.wait_for_selector(sel, timeout=3000)
                login_input = await page.query_selector(sel)
                if login_input and await login_input.is_visible():
                    logger.info(f"Found login input with selector: {sel}")
                    break
                login_input = None
            except Exception:
                continue

        if not login_input:
            # Last resort: find all visible inputs
            all_inputs = await page.query_selector_all('input')
            for inp in all_inputs:
                inp_type = await inp.get_attribute("type") or "text"
                if inp_type in ("text", "email", "tel") and await inp.is_visible():
                    login_input = inp
                    logger.info(f"Found login input via fallback (type={inp_type})")
                    break

        if not login_input:
            # Get page content for debugging
            title = await page.title()
            url = page.url
            raise LoginError(
                f"Cannot find login input field. Page: '{title}' URL: {url}. "
                "TikTok may have changed their login page layout."
            )

        # Find password input
        password_input = await page.query_selector('input[type="password"]')
        if not password_input:
            # Maybe password field appears after entering login
            await login_input.click()
            await self._random_delay(0.3, 0.6)
            await page.keyboard.type(login_id, delay=random.randint(40, 90))
            await self._random_delay(1.0, 2.0)

            # Look for password again
            password_input = await page.query_selector('input[type="password"]')
            if not password_input:
                raise LoginError("Cannot find password input field.")
        else:
            # Type login
            await login_input.click()
            await self._random_delay(0.3, 0.6)
            await login_input.fill("")
            await self._random_delay(0.2, 0.4)
            await page.keyboard.type(login_id, delay=random.randint(40, 90))
            await self._random_delay(0.5, 1.0)

        # Type password
        await password_input.click()
        await self._random_delay(0.3, 0.6)
        await password_input.fill("")
        await self._random_delay(0.2, 0.4)
        await page.keyboard.type(password, delay=random.randint(40, 90))
        await self._random_delay(0.8, 1.5)

    async def _click_login(self, page):
        """Find and click the login/submit button."""
        login_btn = (
            await page.query_selector('button[type="submit"]')
            or await page.query_selector('button[data-e2e="login-button"]')
            or await page.query_selector('button:has-text("Log in")')
            or await page.query_selector('button:has-text("Login")')
            or await page.query_selector('button:has-text("Войти")')
            or await page.query_selector('form button')
        )
        if not login_btn:
            # Try pressing Enter as fallback
            logger.warning("No login button found, pressing Enter instead...")
            await page.keyboard.press("Enter")
        else:
            await self._random_delay(0.3, 0.8)
            await login_btn.click()

        logger.info("Login submitted, waiting for result...")

    async def _wait_for_login(self, browser, page, timeout: int) -> dict:
        """
        Wait for login to complete, checking for errors/CAPTCHA/2FA.
        Returns cookies on success.
        """
        deadline = asyncio.get_event_loop().time() + timeout
        check_count = 0

        while asyncio.get_event_loop().time() < deadline:
            await self._random_delay(2.0, 3.0)
            check_count += 1

            if check_count % 5 == 0:
                logger.info(f"Still waiting for login... (check #{check_count}, url={page.url})")

            # 1. Check for CAPTCHA
            captcha = await page.query_selector(
                '#captcha-verify-image, '
                '.captcha_verify_container, '
                '.captcha-verify-container, '
                '#captcha_container, '
                'div[class*="Captcha"], '
                'div[id*="captcha"], '
                'iframe[src*="captcha"]'
            )
            if captcha:
                is_visible = await captcha.is_visible()
                if is_visible:
                    logger.warning("CAPTCHA detected and visible!")
                    raise CaptchaRequired(
                        "CAPTCHA detected. Use CLI: python -m cli.main auth login --no-headless"
                    )

            # 2. Check for 2FA / verification
            twofa = await page.query_selector(
                '[data-e2e="verification-code-input"], '
                'input[placeholder*="verification" i], '
                'input[placeholder*="code" i]'
            )
            if twofa:
                is_visible = await twofa.is_visible()
                if is_visible:
                    raise TwoFactorRequired(
                        "Two-factor verification required. "
                        "Use CLI: python -m cli.main auth login --no-headless"
                    )

            # 3. Check for error messages
            error_texts = await page.query_selector_all(
                '[data-e2e="login-error-message"], '
                '.error-message, '
                'div[class*="error" i]'
            )
            for error_el in error_texts:
                try:
                    is_visible = await error_el.is_visible()
                    if not is_visible:
                        continue
                    error_text = await error_el.text_content()
                    if error_text and len(error_text.strip()) > 3:
                        lower = error_text.lower()
                        if any(kw in lower for kw in [
                            "incorrect", "wrong", "invalid", "doesn't match",
                            "not found", "doesn't exist", "check your",
                            "не найден", "неверн", "ошиб", "некорр",
                        ]):
                            raise InvalidCredentials(f"Login failed: {error_text.strip()}")
                except InvalidCredentials:
                    raise
                except Exception:
                    continue

            # 4. Check for successful login — session cookies
            if await self._has_session(browser):
                logger.info("Login successful! Session cookies captured.")
                return self._extract_cookies(await browser.cookies("https://www.tiktok.com"))

            # 5. Check if URL changed away from login page
            current_url = page.url
            if "/login" not in current_url and "tiktok.com" in current_url:
                await self._random_delay(2.0, 3.0)
                if await self._has_session(browser):
                    logger.info("Login successful via redirect!")
                    return self._extract_cookies(await browser.cookies("https://www.tiktok.com"))

        raise LoginError(
            f"Login timed out after {timeout} seconds. "
            "Try using CLI: python -m cli.main auth login --no-headless"
        )

    async def _has_session(self, browser) -> bool:
        """Check if session cookies exist in the browser context."""
        cookies = await browser.cookies("https://www.tiktok.com")
        cookie_names = {c["name"] for c in cookies}
        return bool(self.SESSION_COOKIES & cookie_names)

    @staticmethod
    def _extract_cookies(cookies: list[dict]) -> dict:
        """Convert Playwright cookie list to a simple dict."""
        return {c["name"]: c["value"] for c in cookies}

    @staticmethod
    def _safe_name(name: str) -> str:
        """Create a safe directory name from login ID."""
        return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)

    @staticmethod
    async def _random_delay(min_sec: float, max_sec: float):
        """Sleep a random duration to appear more human."""
        await asyncio.sleep(random.uniform(min_sec, max_sec))
