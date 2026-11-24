"""
PRISMA Command Line Interface
=============================
Exposes the CLI entrypoint for pyproject.toml scripts.
"""

from __future__ import annotations

import sys
from download_prisma import main


def run_cli():
    """Main CLI entrypoint for installed package."""
    sys.exit(main() or 0)


if __name__ == "__main__":
    run_cli()
