"""
PRISMA Catalog Search & AOI Parser
==================================
Handles spatial AOI parsing (GeoJSON, Bbox), Solr spatial queries, and product discovery.
Supports both HTTPS and HTTP endpoints.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
import requests

from prisma_pilot.auth import get_authenticated_session
from prisma_pilot.config import config

logger = logging.getLogger("prisma_pilot.search")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Base endpoints
BASE_HTTPS = "https://prisma.asi.it"
BASE_HTTP = "http://prisma.asi.it"


class AOI:
    """Represents an Area of Interest with both Bounding Box and Polygon WKT."""

    def __init__(self, bbox: list[float], wkt: str, raw_geojson: dict[str, Any] | None = None):
        self.min_lon, self.min_lat, self.max_lon, self.max_lat = bbox
        self.bbox = bbox
        self.wkt = wkt
        self.geojson = raw_geojson

    def __repr__(self) -> str:
        return f"AOI(bbox=[{self.min_lon:.4f}, {self.min_lat:.4f}, {self.max_lon:.4f}, {self.max_lat:.4f}])"


def parse_aoi(
    aoi_input: str | Path | dict[str, Any] | list[float] | tuple[float, ...] | AOI,
) -> AOI:
    """
    Parses an AOI from diverse formats:
    - AOI instance (returned directly)
    - GeoJSON file path (str or Path to .geojson / .json)
    - GeoJSON dict (FeatureCollection, Feature, Polygon, MultiPolygon)
    - Bbox list/tuple: [min_lon, min_lat, max_lon, max_lat]
    - Bbox string: "min_lon,min_lat,max_lon,max_lat" or "min_lon min_lat max_lon max_lat"
    """
    if isinstance(aoi_input, AOI):
        return aoi_input

    # 1. Check if string points to a GeoJSON file
    if isinstance(aoi_input, (str, Path)):
        p = Path(aoi_input)
        if not p.is_file():
            for candidate in [Path.cwd() / p, Path.cwd().parent / p, Path(__file__).resolve().parent.parent / p]:
                if candidate.is_file():
                    p = candidate
                    break
        if p.is_file():
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            return _parse_geojson_dict(data)

    # 2. Check if input is a dict (GeoJSON)
    if isinstance(aoi_input, dict):
        return _parse_geojson_dict(aoi_input)

    # 3. Check if input is string representation of bbox or JSON
    if isinstance(aoi_input, str):
        stripped = aoi_input.strip()
        if stripped.startswith("{"):
            try:
                data = json.loads(stripped)
                return _parse_geojson_dict(data)
            except json.JSONDecodeError:
                pass
        # Comma or space separated coordinates
        parts = [p.strip() for p in stripped.replace(",", " ").split() if p.strip()]
        if len(parts) == 4:
            try:
                coords = [float(p) for p in parts]
                return _parse_bbox_coords(coords)
            except ValueError:
                pass

    # 4. Check if list or tuple of 4 coordinates
    if isinstance(aoi_input, (list, tuple)) and len(aoi_input) == 4:
        coords = [float(c) for c in aoi_input]
        return _parse_bbox_coords(coords)

    raise ValueError(
        f"Unable to parse AOI from: {aoi_input}. Expected GeoJSON filepath, GeoJSON dict, "
        "or [min_lon, min_lat, max_lon, max_lat] bbox."
    )


def _parse_bbox_coords(bbox: list[float]) -> AOI:
    min_lon, min_lat, max_lon, max_lat = bbox
    # Ensure min < max
    if min_lon > max_lon:
        min_lon, max_lon = max_lon, min_lon
    if min_lat > max_lat:
        min_lat, max_lat = max_lat, min_lat

    # WKT closed polygon in standard counter-clockwise order
    wkt = (
        f"POLYGON(({min_lon} {min_lat}, {max_lon} {min_lat}, "
        f"{max_lon} {max_lat}, {min_lon} {max_lat}, {min_lon} {min_lat}))"
    )
    return AOI([min_lon, min_lat, max_lon, max_lat], wkt)


def _parse_geojson_dict(data: dict[str, Any]) -> AOI:
    coords_list: list[list[float]] = []

    def extract_coords(geom: dict[str, Any]):
        gtype = geom.get("type", "")
        coordinates = geom.get("coordinates", [])
        if gtype == "Polygon":
            for ring in coordinates:
                for pt in ring:
                    coords_list.append([float(pt[0]), float(pt[1])])
        elif gtype == "MultiPolygon":
            for poly in coordinates:
                for ring in poly:
                    for pt in ring:
                        coords_list.append([float(pt[0]), float(pt[1])])
        elif gtype in ("Point", "MultiPoint", "LineString", "MultiLineString"):
            def recurse_pts(c):
                if isinstance(c[0], (int, float)):
                    coords_list.append([float(c[0]), float(c[1])])
                else:
                    for sub in c:
                        recurse_pts(sub)
            recurse_pts(coordinates)

    dtype = data.get("type", "")
    if dtype == "FeatureCollection":
        for feat in data.get("features", []):
            if feat.get("geometry"):
                extract_coords(feat["geometry"])
    elif dtype == "Feature":
        if data.get("geometry"):
            extract_coords(data["geometry"])
    elif "coordinates" in data:
        extract_coords(data)

    if not coords_list:
        raise ValueError("No valid coordinates found in GeoJSON input.")

    lons = [pt[0] for pt in coords_list]
    lats = [pt[1] for pt in coords_list]
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)

    # Use first polygon exterior ring for exact WKT if available, else bbox polygon
    wkt = (
        f"POLYGON(({min_lon} {min_lat}, {max_lon} {min_lat}, "
        f"{max_lon} {max_lat}, {min_lon} {max_lat}, {min_lon} {min_lat}))"
    )
    return AOI([min_lon, min_lat, max_lon, max_lat], wkt, raw_geojson=data)


def search_prisma(
    aoi: str | Path | dict[str, Any] | list[float] | None = None,
    bbox: list[float] | None = None,
    geojson: str | Path | dict[str, Any] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    max_cloud: float | None = None,
    rows: int = 50,
    session: requests.Session | None = None,
    use_http: bool = False,
) -> list[dict[str, Any]]:
    """
    Search the PRISMA catalog for acquisitions intersecting the specified AOI.

    Parameters:
        aoi: GeoJSON filepath, GeoJSON dict, or bbox coordinates
        bbox: Optional explicit [min_lon, min_lat, max_lon, max_lat]
        geojson: Optional explicit GeoJSON filepath or dict
        start_date: Earliest acquisition date (e.g. '2021-01-01' or ISO format)
        end_date: Latest acquisition date (e.g. '2026-12-31')
        max_cloud: Maximum cloud coverage percentage (0.0 to 100.0)
        rows: Maximum number of records to retrieve from catalog (default: 50)
        session: Optional authenticated requests.Session
        use_http: If True, attempts HTTP protocol first before HTTPS fallback

    Returns:
        List of product dictionaries containing metadata, footprint, and download URLs.
    """
    # Resolve AOI
    target_input = aoi or geojson or bbox
    if target_input is None:
        raise ValueError("Must provide either aoi, geojson, or bbox.")
    parsed_aoi = parse_aoi(target_input)

    if session is None:
        session = get_authenticated_session()

    base_url = BASE_HTTP if use_http else BASE_HTTPS
    service_url = f"{base_url}/prisma-cat/service.php"

    page_size = 100 if rows > 10 else 10
    fq_spatial = f'geom_srpt:"Intersects({parsed_aoi.wkt})"'

    logger.info(f"Querying PRISMA Catalog at {service_url}...")
    logger.info(f"Spatial filter: bbox=[{parsed_aoi.min_lon:.4f}, {parsed_aoi.min_lat:.4f}, {parsed_aoi.max_lon:.4f}, {parsed_aoi.max_lat:.4f}]")

    raw_docs: list[dict[str, Any]] = []
    total_found = 0
    start = 0

    while len(raw_docs) < rows:
        payload = {
            "request": "query",
            "core": "products",
            "rows": str(page_size),
            "start": str(start),
            "fq": fq_spatial,
        }

        r = None
        if use_http:
            saved_cookies = session.cookies.copy()
            try:
                logger.info("Attempting HTTP protocol as requested...")
                r = session.post(service_url, data=payload, timeout=30)
                if r.status_code in (301, 302, 401) or not r.content:
                    logger.info(f"HTTP returned {r.status_code} (PRISMA server requires TLS for authenticated queries).")
                    logger.info("Preserving session credentials and falling back to HTTPS...")
                    session.cookies.clear()
                    session.cookies.update(saved_cookies)
                    service_url = f"{BASE_HTTPS}/prisma-cat/service.php"
                    r = session.post(service_url, data=payload, timeout=30)
            except Exception as e:
                logger.warning(f"HTTP request error: {e}. Restoring session and falling back to HTTPS...")
                session.cookies.clear()
                session.cookies.update(saved_cookies)
                service_url = f"{BASE_HTTPS}/prisma-cat/service.php"
                r = session.post(service_url, data=payload, timeout=30)
        else:
            r = session.post(service_url, data=payload, timeout=30)

        if r.status_code != 200 or not r.content:
            raise RuntimeError(
                f"PRISMA catalog query failed with status {r.status_code}: {r.text[:200]}"
            )

        try:
            data = json.loads(r.content)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Failed to parse JSON response from PRISMA catalog: {e}")

        resp = data.get("response", {})
        total_found = resp.get("numFound", 0)
        batch = resp.get("docs", [])
        if not batch:
            break

        raw_docs.extend(batch)
        start += page_size
        if start >= total_found or len(raw_docs) >= rows:
            break
    logger.info(f"Catalog query returned {total_found} total acquisitions in database (retrieved {len(raw_docs)}).")

    # Filter and format products
    results = []
    for doc in raw_docs:
        start_ts = doc.get("validitystart_dt", "")
        stop_ts = doc.get("validitystop_dt", "")
        cloud_pct = float(doc.get("cloud_pctg_f", 0.0))

        # Date filtering
        if start_date and start_ts and start_ts < start_date:
            continue
        if end_date and stop_ts and stop_ts > end_date:
            continue

        # Cloud filtering
        if max_cloud is not None and cloud_pct > max_cloud:
            continue

        product_id = doc.get("id", "")
        filename = doc.get("filename_s", "")
        clean_id = filename.replace(".DBL", "")

        quicklook = doc.get("quicklook_s", "")
        if quicklook and not quicklook.startswith("http"):
            quicklook = urljoin(BASE_HTTPS, quicklook)

        prod_dict = {
            "id": product_id,
            "filename": filename,
            "clean_id": clean_id,
            "start_time": start_ts,
            "stop_time": stop_ts,
            "cloud_cover": round(cloud_pct, 2),
            "file_type": doc.get("filetype_s", "PRS_L0__EO"),
            "satellite": doc.get("satelliteacronym_s", "PRS"),
            "data_size_bytes": doc.get("datasize_l", 0),
            "data_size_mb": round(doc.get("datasize_l", 0) / (1024 * 1024), 2),
            "geometry": doc.get("geom_srpt", ""),
            "quicklook_url": quicklook,
            "download_url": f"{BASE_HTTPS}/missionselect/download.php?file={clean_id}.zip",
            "http_download_url": f"{BASE_HTTP}/missionselect/download.php?file={clean_id}.zip",
            "raw_doc": doc,
        }
        results.append(prod_dict)

    logger.info(f"Filtered to {len(results)} matching acquisitions after date/cloud criteria.")
    return results


def get_user_orders(
    session: requests.Session | None = None,
    use_http: bool = False,
) -> list[dict[str, Any]]:
    """
    Retrieve list of past and current orders submitted by the authenticated user.
    """
    if session is None:
        session = get_authenticated_session()

    base_url = BASE_HTTP if use_http else BASE_HTTPS
    url = f"{base_url}/prisma-orders-status/"

    username = config.username
    params = {"userId": f"{username}", "externalOrderId": "extref%"}

    if use_http:
        saved_cookies = session.cookies.copy()
        try:
            logger.info("Attempting HTTP protocol for orders query...")
            r = session.get(url, params=params, timeout=15)
            if r.status_code in (301, 302, 401) or not r.content:
                logger.info(f"HTTP returned {r.status_code}. Preserving session cookies and falling back to HTTPS...")
                session.cookies.clear()
                session.cookies.update(saved_cookies)
                url = f"{BASE_HTTPS}/prisma-orders-status/"
                r = session.get(url, params=params, timeout=15)
            if r.status_code == 200 and r.content:
                return r.json()
        except Exception as e:
            logger.debug(f"HTTP orders query error: {e}. Falling back to HTTPS...")
            session.cookies.clear()
            session.cookies.update(saved_cookies)
            url = f"{BASE_HTTPS}/prisma-orders-status/"
            r = session.get(url, params=params, timeout=15)
            if r.status_code == 200 and r.content:
                return r.json()
    else:
        try:
            r = session.get(url, params=params, timeout=15)
            if r.status_code == 200 and r.content:
                return r.json()
        except Exception as e:
            logger.debug(f"Orders status query notice: {e}")

    # Fallback to direct URL-encoded query
    encoded_url = f"{BASE_HTTPS}/prisma-orders-status/?userId={username.replace('$', '%24')}&externalOrderId=extref%25"
    r = session.get(encoded_url, timeout=15)
    if r.status_code == 200 and r.content:
        return r.json()
    return []
