"""
PRISMA Configuration & Credentials
==================================
Manages environment variables, authentication credentials, and cache directories.
"""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# Check explicit env file override if specified
env_file_override = os.getenv("PRISMA_ENV_FILE")

# Search candidate locations portable across OS/environments
CANDIDATE_DOTENVS = [
    Path.home() / ".config" / "prisma_pilot" / ".env",
    Path.home() / ".prisma_pilot" / ".env",
    Path(__file__).resolve().parent.parent / ".env",
    Path(__file__).resolve().parent / ".env",
    Path.cwd() / ".env",
    Path.cwd() / "prisma_pilot" / ".env",
]

if env_file_override and Path(env_file_override).is_file():
    load_dotenv(env_file_override, override=True)
else:
    for p in CANDIDATE_DOTENVS:
        if p.is_file():
            load_dotenv(p, override=True)

CACHE_DIR = Path(os.getenv("PRISMA_CACHE_DIR", str(Path.home() / ".cache" / "prisma_pilot")))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

SESSION_FILE = CACHE_DIR / "session.json"


class PrismaConfig:
    @property
    def username(self) -> str:
        return (os.getenv("PRISMA_USER") or os.getenv("PRISMA_USERNAME") or "").strip()

    @property
    def password(self) -> str:
        return (os.getenv("PRISMA_PASS") or os.getenv("PRISMA_PASSWORD") or "").strip()

    @property
    def phpsessid(self) -> str:
        return os.getenv("PRISMA_PHPSESSID", os.getenv("PRISMA_COOKIE", "")).strip()

    @property
    def has_credentials(self) -> bool:
        return bool(self.username and self.password)

    @property
    def has_session(self) -> bool:
        return bool(self.phpsessid or SESSION_FILE.exists())


config = PrismaConfig()
