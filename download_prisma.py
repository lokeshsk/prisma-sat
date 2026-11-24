#!/usr/bin/env python3
"""
Automated PRISMA Satellite Data Acquisition Script
==================================================
Convenience wrapper script around `prisma_pilot.cli`.
Can be run directly via `python download_prisma.py ...` or via `prisma-sat` CLI.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on sys.path when running from source
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

from prisma_pilot.cli import main, run_cli

if __name__ == "__main__":
    run_cli()
