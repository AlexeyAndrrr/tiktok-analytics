import secrets
import threading
import webbrowser
from urllib.parse import urlencode

from flask import Flask, request

from auth.pkce import generate_pkce_pair
from config import settings


class OAuthCallbackServer:
    """Local Flask server that handles the TikTok OAuth2 callback."""

    def __init__(self):
        self.app = Flask(__name__)
        self.auth_code = None
        self.error = None
        self.state = secrets.token_urlsafe(32)
        self.code_verifier, self.code_challenge = generate_pkce_pair()
        self._server = None

        @self.app.route("/callback")
        def callback():
            returned_state = request.args.get("state")
            if returned_state != self.state:
                self.error = "State mismatch — possible CSRF attack"
                return "<h2>Error: state mismatch</h2><p>You can close this window.</p>"

            error = request.args.get("error")
            if error:
                self.error = f"{error}: {request.args.get('error_description', '')}"
                return f"<h2>Authorization failed</h2><p>{self.error}</p><p>You can close this window.</p>"

            self.auth_code = request.args.get("code")
            if not self.auth_code:
                self.error = "No authorization code received"
                return "<h2>Error: no code</h2><p>You can close this window.</p>"

            threading.Timer(1.0, self._shutdown).start()
            return "<h2>Authorization successful!</h2><p>You can close this window and return to the terminal.</p>"

    def _shutdown(self):
        if self._server:
            self._server.shutdown()

    def get_authorization_url(self) -> str:
        """Build the TikTok OAuth2 authorization URL."""
        params = {
            "client_key": settings.TIKTOK_CLIENT_KEY,
            "response_type": "code",
            "scope": settings.OAUTH_SCOPES,
            "redirect_uri": settings.OAUTH_REDIRECT_URI,
            "state": self.state,
            "code_challenge": self.code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{settings.TIKTOK_AUTH_URL}?{urlencode(params)}"

    def start_and_wait(self) -> tuple[str | None, str | None]:
        """
        Open browser for authorization and wait for callback.
        Returns (auth_code, error).
        """
        auth_url = self.get_authorization_url()
        webbrowser.open(auth_url)

        from werkzeug.serving import make_server
        self._server = make_server("localhost", settings.OAUTH_PORT, self.app)
        self._server.serve_forever()

        return self.auth_code, self.error
