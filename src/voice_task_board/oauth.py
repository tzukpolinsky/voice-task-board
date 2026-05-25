from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import httpx


logger = logging.getLogger(__name__)


GOOGLE_CLIENT_ID = "709314449728-3j0ip56lr0uvbpreb136p2mpq87o63tv.apps.googleusercontent.com"
GOOGLE_CLIENT_SECRET = "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"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_SCOPE = "https://www.googleapis.com/auth/tasks"

REDIRECT_PORT = 54321
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"


class OAuthError(Exception):
    pass


def start_google_oauth() -> dict[str, Any]:
    return _run_pkce_flow(
        auth_url=GOOGLE_AUTH_URL,
        token_url=GOOGLE_TOKEN_URL,
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scope=GOOGLE_SCOPE,
    )


def refresh_google_token(tokens: dict[str, Any]) -> dict[str, Any]:
    return _refresh(GOOGLE_TOKEN_URL, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, tokens)


def _refresh(token_url: str, client_id: str, client_secret: str, tokens: dict[str, Any]) -> dict[str, Any]:
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise OAuthError("No refresh_token stored")
    data: dict[str, str] = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    if client_secret:
        data["client_secret"] = client_secret
    resp = httpx.post(token_url, data=data, timeout=15)
    resp.raise_for_status()
    new_tokens: dict[str, Any] = resp.json()
    if "refresh_token" not in new_tokens:
        new_tokens["refresh_token"] = refresh_token
    return new_tokens


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _run_pkce_flow(
    auth_url: str,
    token_url: str,
    client_id: str,
    client_secret: str,
    scope: str,
) -> dict[str, Any]:

    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)

    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": scope,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",  # Google: get refresh_token
        "prompt": "consent",
    }
    full_url = auth_url + "?" + urllib.parse.urlencode(params)

    # Capture the callback on a local HTTP server
    result: dict[str, str] = {}
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            result["code"] = qs.get("code", [""])[0]
            result["state"] = qs.get("state", [""])[0]
            result["error"] = qs.get("error", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><body><h2>Connected! You can close this tab.</h2></body></html>")
            done.set()

        def log_message(self, *args: Any) -> None:
            pass  # suppress console noise

    server = HTTPServer(("localhost", REDIRECT_PORT), Handler)
    server_thread = threading.Thread(target=server.handle_request, daemon=True)
    server_thread.start()

    webbrowser.open(full_url)
    logger.info("Opened browser for Google OAuth")

    done.wait(timeout=120)
    server.server_close()

    if result.get("error"):
        raise OAuthError(f"OAuth error from Google: {result['error']}")
    if not result.get("code"):
        raise OAuthError("OAuth timed out or no code received")
    if result.get("state") != state:
        raise OAuthError("OAuth state mismatch — possible CSRF")

    token_data: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": result["code"],
        "redirect_uri": REDIRECT_URI,
        "client_id": client_id,
        "code_verifier": verifier,
    }
    if client_secret:
        token_data["client_secret"] = client_secret
    resp = httpx.post(token_url, data=token_data, timeout=15)
    if not resp.is_success:
        logger.error(f"Token exchange failed {resp.status_code}: {resp.text}")
        resp.raise_for_status()
    tokens: dict[str, Any] = resp.json()
    logger.info("Google OAuth tokens obtained")
    return tokens
