"""
PRISMA Pilot Toolkit
====================
Standalone pilot for ASI PRISMA Hyperspectral Satellite data:
- Authentication & Session Management (WSO2 OAuth2 & Session Caching)
- Spatial AOI Parsing (GeoJSON files/dicts and Bounding Box arrays/strings)
- Solr Spatial Catalog Discovery
- Resilient streaming download pipeline with Range resumption and HDF5 extraction
- Processing order dispatch and order history tracking
"""

from prisma_pilot.config import config
from prisma_pilot.auth import get_authenticated_session, verify_session, ensure_authorized
from prisma_pilot.search import AOI, parse_aoi, search_prisma, get_user_orders
from prisma_pilot.downloader import download_product, download_stream, order_processing, validate_file_integrity, extract_prisma_archive

__version__ = "0.2.0"
__all__ = [
    "config",
    "get_authenticated_session",
    "verify_session",
    "ensure_authorized",
    "AOI",
    "parse_aoi",
    "search_prisma",
    "get_user_orders",
    "download_product",
    "download_stream",
    "order_processing",
    "validate_file_integrity",
    "extract_prisma_archive",
]

