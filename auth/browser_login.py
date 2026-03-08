"""Automated TikTok login via Playwright browser automation."""

import asyncio
import random
import logging

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


class BrowserLogin:
    """Automates TikTok login via Playwright and captures session cookies."""

    LOGIN_URL = "https://www.tiktok.com/login/phone-email/email"
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

        async with async_playwright() as pw:
            browser = await pw.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=headless,
                viewport={"width": 1280, "height": 720},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                locale="en-US",
                ignore_https_errors=True,
            )

            try:
                page = browser.pages[0] if browser.pages else await browser.new_page()

                # Mask webdriver flag
                await page.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                )

                # Navigate to login page
                logger.info("Navigating to TikTok login page...")
                await page.goto(self.LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
                await self._random_delay(1.0, 2.5)

                # Check if already logged in (cookies from persistent context)
                if await self._has_session(browser):
                    logger.info("Already logged in from previous session.")
                    return self._extract_cookies(await browser.cookies("https://www.tiktok.com"))

                # Find and fill login form
                await self._fill_credentials(page, login_id, password)

                # Click login button
                await self._click_login(page)

                # Wait for result
                cookies = await self._wait_for_login(browser, page, timeout)
                return cookies

            finally:
                await browser.close()

    async def _fill_credentials(self, page, login_id: str, password: str):
        """Fill in the login form fields with human-like delays."""
        # Wait for the login form
        try:
            await page.wait_for_selector(
                'input[name="username"], input[placeholder*="email" i], input[placeholder*="phone" i], input[type="text"]',
                timeout=15000,
            )
        except Exception:
            raise LoginError("Login form not found. TikTok may have changed their page layout.")

        # Find login input
        login_input = (
            await page.query_selector('input[name="username"]')
            or await page.query_selector('input[placeholder*="email" i]')
            or await page.query_selector('input[placeholder*="phone" i]')
            or await page.query_selector('form input[type="text"]')
        )
        if not login_input:
            raise LoginError("Cannot find login input field.")

        # Find password input
        password_input = await page.query_selector('input[type="password"]')
        if not password_input:
            raise LoginError("Cannot find password input field.")

        # Clear and type login
        await login_input.click()
        await self._random_delay(0.3, 0.6)
        await login_input.fill("")
        await page.keyboard.type(login_id, delay=random.randint(30, 80))
        await self._random_delay(0.5, 1.0)

        # Clear and type password
        await password_input.click()
        await self._random_delay(0.3, 0.6)
        await password_input.fill("")
        await page.keyboard.type(password, delay=random.randint(30, 80))
        await self._random_delay(0.5, 1.0)

    async def _click_login(self, page):
        """Find and click the login/submit button."""
        login_btn = (
            await page.query_selector('button[type="submit"]')
            or await page.query_selector('button[data-e2e="login-button"]')
            or await page.query_selector('form button')
        )
        if not login_btn:
            raise LoginError("Cannot find login button.")

        await self._random_delay(0.3, 0.8)
        await login_btn.click()
        logger.info("Login button clicked, waiting for result...")

    async def _wait_for_login(self, browser, page, timeout: int) -> dict:
        """
        Wait for login to complete, checking for errors/CAPTCHA/2FA.
        Returns cookies on success.
        """
        deadline = asyncio.get_event_loop().time() + timeout

        while asyncio.get_event_loop().time() < deadline:
            await self._random_delay(1.5, 2.5)

            # Check for CAPTCHA
            captcha = await page.query_selector(
                '#captcha-verify-image, .captcha_verify_container, '
                '[class*="captcha" i], iframe[src*="captcha"]'
            )
            if captcha:
                if browser.contexts[0] if hasattr(browser, 'contexts') else True:
                    logger.warning("CAPTCHA detected!")
                    raise CaptchaRequired(
                        "CAPTCHA detected. Run with --no-headless to solve it manually, "
                        "or try again later."
                    )

            # Check for 2FA / verification
            twofa = await page.query_selector(
                '[data-e2e="verification-code-input"], '
                '[class*="verify" i]:not([class*="captcha"]), '
                'input[placeholder*="verification" i]'
            )
            if twofa:
                raise TwoFactorRequired(
                    "Two-factor verification required. "
                    "Run with --no-headless to complete verification manually."
                )

            # Check for error messages (wrong password, etc.)
            error_el = await page.query_selector(
                '[data-e2e="login-error-message"], '
                '[class*="error" i][class*="message" i], '
                '.tiktok-login-error'
            )
            if error_el:
                error_text = await error_el.text_content()
                if error_text and any(kw in error_text.lower() for kw in [
                    "incorrect", "wrong", "invalid", "doesn't match",
                    "не найден", "неверн", "ошиб",
                ]):
                    raise InvalidCredentials(f"Login failed: {error_text.strip()}")

            # Check for successful login — session cookies
            if await self._has_session(browser):
                logger.info("Login successful! Session cookies captured.")
                return self._extract_cookies(await browser.cookies("https://www.tiktok.com"))

            # Check if URL changed away from login page
            current_url = page.url
            if "/login" not in current_url and "tiktok.com" in current_url:
                # Might have redirected to home/foryou
                await self._random_delay(1.0, 2.0)
                if await self._has_session(browser):
                    logger.info("Login successful! Redirected to home.")
                    return self._extract_cookies(await browser.cookies("https://www.tiktok.com"))

        raise LoginError(f"Login timed out after {timeout} seconds.")

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
