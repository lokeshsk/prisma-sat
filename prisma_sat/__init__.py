"""
PRISMA-SAT
==========
High-level Python client and CLI to search, order, and download
ASI PRISMA hyperspectral satellite data by Area of Interest (AOI).
"""

from __future__ import annotations

from prisma_pilot import (
    AOI,
    config,
    download_product,
    download_stream,
    ensure_authorized,
    extract_prisma_archive,
    get_authenticated_session,
    get_user_orders,
    order_processing,
    parse_aoi,
    search_prisma,
    validate_file_integrity,
    verify_session,
    __version__,
)

__all__ = [
    "AOI",
    "config",
    "download_product",
    "download_stream",
    "ensure_authorized",
    "extract_prisma_archive",
    "get_authenticated_session",
    "get_user_orders",
    "order_processing",
    "parse_aoi",
    "search_prisma",
    "validate_file_integrity",
    "verify_session",
    "__version__",
]
