import hashlib
import secrets
import base64


def generate_pkce_pair() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge pair."""
    code_verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge
