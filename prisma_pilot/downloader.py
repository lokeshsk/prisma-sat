"""
PRISMA Download Pipeline & Order Manager
========================================
Handles chunked streaming downloads with resumption, integrity validation,
ZIP archive extraction, and processing order requests.
Supports both HTTPS and HTTP protocols.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import zipfile
from pathlib import Path
from typing import Any
import requests

from prisma_pilot.auth import get_authenticated_session
from prisma_pilot.config import config

logger = logging.getLogger("prisma_pilot.downloader")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Magic bytes
ZIP_MAGIC = b"PK\x03\x04"
HDF5_MAGIC = b"\x89HDF\r\n\x1a\n"

CHUNK_SIZE = 1024 * 1024  # 1 MB chunks


def format_size(bytes_num: int) -> str:
    """Format bytes into human-readable string (KB, MB, GB)."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_num < 1024.0:
            return f"{bytes_num:.1f} {unit}"
        bytes_num /= 1024.0
    return f"{bytes_num:.1f} PB"


def validate_file_integrity(file_path: Path) -> str:
    """
    Validates file magic bytes to determine format and ensure the file is not corrupted or an HTML error page.
    Returns: 'zip', 'hdf5', or raises ValueError.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(file_path, "rb") as f:
        header = f.read(8)

    if header.startswith(ZIP_MAGIC):
        return "zip"
    elif header.startswith(HDF5_MAGIC):
        return "hdf5"
    elif header.startswith(b"<!DOCT") or header.startswith(b"<html") or header.startswith(b"{\"message"):
        with open(file_path, "r", errors="ignore") as f:
            sample = f.read(200)
        raise ValueError(f"Downloaded file is an HTML or JSON error page, not satellite data: {sample}")
    else:
        # Check if it is a valid zip anyway (some zips have leading bytes)
        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                if zf.namelist():
                    return "zip"
        except Exception:
            pass
        raise ValueError(f"File {file_path} failed integrity verification (header: {header!r}).")


def extract_prisma_archive(zip_path: Path, output_dir: Path) -> Path | None:
    """
    Extracts the PRISMA HDF5 (.he5) data cube from a downloaded .zip archive.
    Returns the path to the extracted .he5 file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    he5_path = None
    logger.info(f"Extracting PRISMA archive: {zip_path.name}...")

    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.namelist():
            target_path = output_dir / member
            if not target_path.exists():
                zf.extract(member, output_dir)
            if member.endswith(".he5"):
                he5_path = target_path

    if he5_path and he5_path.exists():
        logger.info(f"Successfully extracted HDF5 data cube: {he5_path.name} ({format_size(he5_path.stat().st_size)})")
    return he5_path


def download_stream(
    url: str,
    output_path: Path,
    session: requests.Session,
    allow_resume: bool = True,
) -> Path:
    """
    Downloads a remote file with streaming chunks, HTTP Range resumption, and progress reporting.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = output_path.with_suffix(output_path.suffix + ".part")

    existing_bytes = 0
    headers = {}
    if allow_resume and part_path.exists():
        existing_bytes = part_path.stat().st_size
        if existing_bytes > 0:
            headers["Range"] = f"bytes={existing_bytes}-"
            logger.info(f"Resuming download from byte {existing_bytes} ({format_size(existing_bytes)})...")

    response = session.get(url, stream=True, headers=headers, timeout=60)

    # Check for Range not satisfiable or server ignored range
    if response.status_code == 416:
        # Existing file is complete
        part_path.rename(output_path)
        return output_path
    elif response.status_code == 206:
        # Partial content response
        mode = "ab"
        content_range = response.headers.get("Content-Range", "")
        if "/" in content_range:
            total_bytes = int(content_range.split("/")[-1])
        else:
            total_bytes = existing_bytes + int(response.headers.get("Content-Length", 0))
    elif response.status_code == 200:
        # Fresh download
        mode = "wb"
        existing_bytes = 0
        total_bytes = int(response.headers.get("Content-Length", 0))
    else:
        raise RuntimeError(
            f"Download failed with HTTP status {response.status_code}: {response.text[:200]}"
        )

    downloaded = existing_bytes
    start_time = time.time()
    last_print = start_time

    with open(part_path, mode) as f:
        for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
            if not chunk:
                continue
            f.write(chunk)
            downloaded += len(chunk)

            # Progress bar reporting
            now = time.time()
            if now - last_print >= 0.5 or (total_bytes and downloaded >= total_bytes):
                last_print = now
                elapsed = max(0.001, now - start_time)
                speed = (downloaded - existing_bytes) / elapsed
                speed_str = f"{format_size(int(speed))}/s"

                if total_bytes > 0:
                    pct = (downloaded / total_bytes) * 100.0
                    eta_sec = int((total_bytes - downloaded) / max(1, speed))
                    bar_len = 25
                    filled = int(bar_len * downloaded / total_bytes)
                    bar = "=" * filled + "-" * (bar_len - filled)
                    sys.stdout.write(
                        f"\r  [{bar}] {pct:5.1f}% | {format_size(downloaded)}/{format_size(total_bytes)} | {speed_str} | ETA: {eta_sec}s"
                    )
                else:
                    sys.stdout.write(
                        f"\r  Downloaded: {format_size(downloaded)} | {speed_str}"
                    )
                sys.stdout.flush()

    sys.stdout.write("\n")
    sys.stdout.flush()

    # Move .part to final output path
    part_path.rename(output_path)
    logger.info(f"Download complete: {output_path.name} ({format_size(output_path.stat().st_size)})")
    return output_path


def download_product(
    product_id_or_url: str,
    output_dir: str | Path = "./downloads",
    session: requests.Session | None = None,
    use_http: bool = False,
    extract: bool = True,
) -> dict[str, Any]:
    """
    Downloads a PRISMA product package (.zip or .he5).

    Parameters:
        product_id_or_url: Product ID (e.g. 'PRS_L1_STD_OFFL_20260130060212_20260130060216_0001')
                           or a direct HTTP/HTTPS download URL.
        output_dir: Local destination directory.
        session: Optional authenticated requests.Session.
        use_http: Whether to attempt HTTP before HTTPS.
        extract: Whether to extract .he5 from downloaded .zip archives.

    Returns:
        Dictionary with status, file paths, size, and format.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if session is None:
        session = get_authenticated_session()

    raw_target = product_id_or_url.strip()
    is_url = raw_target.startswith("http://") or raw_target.startswith("https://")

    if is_url:
        download_url = raw_target
        # Deduce filename from URL
        url_name = download_url.split("?")[0].split("/")[-1] or "prisma_product.zip"
        if not (url_name.endswith(".zip") or url_name.endswith(".he5")):
            url_name += ".zip"
        target_path = out_dir / url_name
    else:
        # Clean product ID
        clean_id = raw_target
        for ext in [".zip", ".he5", ".DBL", ".DBL-0001"]:
            if clean_id.endswith(ext):
                clean_id = clean_id[:-len(ext)]

        filename = f"{clean_id}.zip"
        target_path = out_dir / filename

        proto = "http" if use_http else "https"
        download_url = f"{proto}://prisma.asi.it/missionselect/download.php?file={filename}"

    # If already downloaded and valid, return early
    if target_path.exists() and target_path.stat().st_size > 0:
        try:
            fmt = validate_file_integrity(target_path)
            logger.info(f"File already exists and verified ({fmt}): {target_path}")
            he5_file = None
            if extract and fmt == "zip":
                he5_file = extract_prisma_archive(target_path, out_dir)
            return {
                "status": "success",
                "zip_path": str(target_path),
                "he5_path": str(he5_file) if he5_file else None,
                "file_size_bytes": target_path.stat().st_size,
                "format": fmt,
            }
        except ValueError:
            logger.warning("Existing local file is invalid or incomplete. Re-downloading...")
            target_path.unlink()

    # Attempt download
    logger.info(f"Initiating download: {download_url}")
    saved_cookies = session.cookies.copy()
    try:
        downloaded_file = download_stream(download_url, target_path, session)
    except Exception as e:
        if use_http and download_url.startswith("http://"):
            logger.info(f"HTTP download notice ({e}). Restoring session cookies and retrying via HTTPS...")
            session.cookies.clear()
            session.cookies.update(saved_cookies)
            https_url = "https://" + download_url[7:]
            downloaded_file = download_stream(https_url, target_path, session)
        elif not use_http and download_url.startswith("https://"):
            logger.info(f"HTTPS download notice ({e}). Trying HTTP endpoint as fallback...")
            http_url = "http://" + download_url[8:]
            try:
                downloaded_file = download_stream(http_url, target_path, session)
            except Exception:
                session.cookies.clear()
                session.cookies.update(saved_cookies)
                raise e
        else:
            raise e

    # Validate integrity
    fmt = validate_file_integrity(downloaded_file)

    he5_path = None
    if extract and fmt == "zip":
        he5_path = extract_prisma_archive(downloaded_file, out_dir)

    return {
        "status": "success",
        "zip_path": str(downloaded_file),
        "he5_path": str(he5_path) if he5_path else None,
        "file_size_bytes": downloaded_file.stat().st_size,
        "format": fmt,
    }


def order_processing(
    product_id: str,
    processor: str = "L2D",
    session: requests.Session | None = None,
    use_http: bool = False,
) -> dict[str, Any]:
    """
    Submits a processing order for a PRISMA Level 0 acquisition to produce
    Level 1 (L1_A_EO), Level 2B (L2B), Level 2C (L2C), or Level 2D (L2D).
    """
    if session is None:
        session = get_authenticated_session()

    base_url = "http://prisma.asi.it" if use_http else "https://prisma.asi.it"
    url = f"{base_url}/prisma-cat/service.php?request=process"

    # Normalize ID
    clean_id = product_id
    if clean_id.endswith(".zip"):
        clean_id = clean_id[:-4]
    filename_s = clean_id if clean_id.endswith(".DBL") else f"{clean_id}.DBL"

    processor_name = "L1_A_EO" if processor.upper() in ("L1", "L1A", "L1_A_EO") else processor.upper()

    order_payload = {
        "INPUT_NAME": filename_s,
        "id": f"{filename_s}-0001",
        "processorname": processor_name,
        "base_params": {},
        "proc_spec_params": {},
    }

    logger.info(f"Submitting processing order for {filename_s} to {processor_name}...")
    headers = {"Content-Type": "application/json"}
    r = session.post(url, data=json.dumps(order_payload), headers=headers, timeout=30)

    if r.status_code == 200:
        logger.info(f"Order successfully submitted: {r.text}")
        try:
            return r.json()
        except Exception:
            return {"status": "submitted", "response": r.text}
    else:
        raise RuntimeError(f"Order submission failed ({r.status_code}): {r.text}")
