"""
PRISMA Authentication & Session Management
===========================================
Handles WSO2 Identity Server authentication, OAuth2 consent, and cookie persistence.
Supports cached session reuse and automated headless Chrome CDP fallback.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urljoin
import requests

from prisma_pilot.config import config, CACHE_DIR, SESSION_FILE

logger = logging.getLogger("prisma_pilot.auth")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

DOCS_CHECK_URL = "https://prisma.asi.it/missionselect/docs.php"
CATALOG_CLIENT_URL = "https://prisma.asi.it/js-cat-client-prisma-src/"
MISSIONSELECT_URL = "https://prisma.asi.it/missionselect/"


def create_base_session(cookies: dict[str, str] | None = None) -> requests.Session:
    """Create a configured requests.Session with standard browser headers and cookies."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    if cookies:
        for name, value in cookies.items():
            session.cookies.set(name, value, domain="prisma.asi.it", path="/")
    return session


def ensure_authorized(session: requests.Session, target_url: str) -> bool:
    """
    Follows OAuth 302 redirect chains to exchange authorization codes and establish
    session cookies (such as pastr-*). Rewrites any internal http:// redirects to https://
    to ensure Secure-flagged cookies are not dropped by the client.
    Returns True if target_url resolved successfully (HTTP 200) without redirecting to login.do.
    """
    curr_url = target_url
    for _ in range(6):
        try:
            r = session.get(curr_url, allow_redirects=False, timeout=15)
        except Exception as e:
            logger.debug(f"Error checking authorization at {curr_url}: {e}")
            return False

        if r.status_code in (301, 302, 303, 307):
            loc = r.headers.get("Location")
            if not loc:
                break
            if "login.do" in loc:
                return False
            # Upgrade redirect URL to https if server sent http
            if loc.startswith("http://prisma.asi.it"):
                loc = "https://prisma.asi.it" + loc[20:]
            elif loc.startswith("http://"):
                loc = "https://" + loc[7:]
            curr_url = urljoin(curr_url, loc)
        elif r.status_code == 200:
            if "login.do" in curr_url or "loginForm" in r.text[:2000]:
                return False
            return True
        else:
            return False
    return False


def verify_session(session: requests.Session) -> bool:
    """
    Verify whether the current session cookies are authenticated and active.
    Validates by ensuring access to both missionselect and catalog services.
    """
    return ensure_authorized(session, DOCS_CHECK_URL) and ensure_authorized(session, CATALOG_CLIENT_URL)


def load_cached_session() -> dict[str, str] | None:
    """Load cached session cookies from disk if available."""
    if config.phpsessid:
        return {"PHPSESSID": config.phpsessid}

    if SESSION_FILE.exists():
        try:
            with open(SESSION_FILE, "r") as f:
                data = json.load(f)
            if isinstance(data, dict) and "PHPSESSID" in data:
                return data
        except Exception as e:
            logger.debug(f"Failed to read session file: {e}")
    return None


def save_cached_session(cookies: dict[str, str]) -> None:
    """Persist session cookies to session.json."""
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SESSION_FILE, "w") as f:
        json.dump(cookies, f, indent=2)
    logger.info(f"Saved active session cookies to {SESSION_FILE}")


async def _run_chrome_cdp_login(username: str, password: str, port: int = 9222) -> dict[str, str]:
    """Automates headless Chrome CDP to submit credentials and extract session cookies."""
    import shutil
    import tempfile
    import websockets

    # Clean up any orphan chrome test processes
    subprocess.run(
        ["pkill", "-f", f"remote-debugging-port={port}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1)

    user_data_dir = tempfile.mkdtemp(prefix="chrome_prisma_")
    chrome_proc = subprocess.Popen([
        "google-chrome",
        "--headless=new",
        "--disable-gpu",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "https://prisma.asi.it/missionselect/",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    time.sleep(2)
    try:
        tabs = requests.get(f"http://localhost:{port}/json", timeout=5).json()
        pages = [t for t in tabs if t.get("type") == "page"]
        if not pages:
            raise RuntimeError("No active page tab found in Chrome")
        ws_url = pages[0].get("webSocketDebuggerUrl")
        if not ws_url:
            raise RuntimeError("Failed to obtain Chrome CDP WebSocket URL")

        async with websockets.connect(ws_url) as ws:
            msg_id = 1

            async def cmd(method: str, params: dict | None = None) -> dict:
                nonlocal msg_id
                cid = msg_id
                msg_id += 1
                await ws.send(json.dumps({"id": cid, "method": method, "params": params or {}}))
                while True:
                    raw = await ws.recv()
                    data = json.loads(raw)
                    if data.get("id") == cid:
                        return data.get("result", {})

            await cmd("Page.enable")
            await cmd("Network.enable")
            logger.info("Connecting to PRISMA login page via Chrome CDP...")

            submitted = False
            approved = False
            reached_portal = False

            for _ in range(35):
                await asyncio.sleep(1)
                curr_url = (await cmd("Runtime.evaluate", {"expression": "window.location.href"})).get("result", {}).get("value", "")
                if "login.do" in curr_url and not submitted:
                    logger.info("Submitting login credentials to WSO2 Identity Server...")
                    js_fill = f"""
                    document.getElementById('username').value = {json.dumps(username)};
                    document.getElementById('password').value = {json.dumps(password)};
                    document.getElementById('loginForm').submit();
                    """
                    await cmd("Runtime.evaluate", {"expression": js_fill})
                    submitted = True
                elif "oauth2_consent.do" in curr_url and not approved:
                    logger.info("Approving OAuth consent dialog...")
                    await cmd("Runtime.evaluate", {"expression": "approvedAlways()"})
                    approved = True
                elif "missionselect" in curr_url and "login.do" not in curr_url and submitted:
                    logger.info("Successfully reached PRISMA portal in browser.")
                    reached_portal = True
                    break

            if not reached_portal:
                raise RuntimeError(f"Chrome login timed out waiting for redirect to PRISMA portal. Final URL: {curr_url}")

            # Extract cookies for prisma.asi.it
            cookies_res = await cmd("Network.getCookies", {
                "urls": ["https://prisma.asi.it", "http://prisma.asi.it"]
            })
            cookie_dict = {}
            for c in cookies_res.get("cookies", []):
                domain = c.get("domain", "")
                if "prisma.asi.it" in domain:
                    cookie_dict[c["name"]] = c["value"]

            logger.info(f"Captured {len(cookie_dict)} authentication cookies from browser")
            return cookie_dict
    finally:
        chrome_proc.terminate()
        try:
            chrome_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            chrome_proc.kill()
        shutil.rmtree(user_data_dir, ignore_errors=True)


def perform_catalog_handshake(session: requests.Session) -> requests.Session:
    """
    Performs the secondary OAuth authorization handshake required by the PRISMA Catalog
    client (/js-cat-client-prisma-src/) to establish the pastr-* session cookie.
    """
    ensure_authorized(session, CATALOG_CLIENT_URL)
    return session


def get_authenticated_session(force_refresh: bool = False) -> requests.Session:
    """
    Retrieves a fully authenticated requests.Session for PRISMA.
    Uses cached session if valid; otherwise launches headless Chrome CDP to re-authenticate.
    """
    if not force_refresh:
        cached = load_cached_session()
        if cached:
            session = create_base_session(cached)
            if verify_session(session):
                logger.info("Reusing valid cached PRISMA session")
                save_cached_session({c.name: c.value for c in session.cookies})
                return session
            logger.info("Cached PRISMA session expired. Re-authenticating...")

    if not config.has_credentials:
        raise ValueError(
            "PRISMA credentials not found. Please set PRISMA_USER (or PRISMA_USERNAME) and "
            "PRISMA_PASS (or PRISMA_PASSWORD) in .env"
        )

    logger.info(f"Authenticating as {config.username}...")
    cookies = asyncio.run(_run_chrome_cdp_login(config.username, config.password))

    session = create_base_session(cookies)
    perform_catalog_handshake(session)
    if not verify_session(session):
        raise RuntimeError("Authentication completed but session verification failed.")

    save_cached_session({c.name: c.value for c in session.cookies})
    logger.info("Authentication successful and verified.")
    return session
