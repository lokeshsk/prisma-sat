#!/usr/bin/env python3
"""
Automated PRISMA Satellite Data Acquisition Script
==================================================
Searches and downloads hyperspectral data from the ASI PRISMA mission
for any given Area of Interest (AOI) in GeoJSON or Bounding Box format.

Features:
- Automated credentials loading from .env (PRISMA_USER / PRISMA_PASS)
- Headless Chrome CDP OAuth authentication with session caching
- Spatial AOI parsing for both GeoJSON (files or dicts) and Bounding Box
- Catalog discovery via ASI PRISMA Solr spatial query engine
- Streaming chunked download with HTTP Range resumption and integrity verification
- Support for both HTTPS and HTTP protocols (--http)
- User orders cross-referencing and automatic ZIP archive extraction
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Add project root to path if running directly
current_dir = Path(__file__).resolve().parent
if str(current_dir.parent) not in sys.path:
    sys.path.insert(0, str(current_dir.parent))
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

from prisma_pilot.config import config, SESSION_FILE
from prisma_pilot.auth import get_authenticated_session, verify_session
from prisma_pilot.search import parse_aoi, search_prisma, get_user_orders
from prisma_pilot.downloader import download_product, order_processing, format_size


def print_banner():
    print(r"""
=============================================================================
  ____  ____  ___ ____  __  __    _       ____  _ _       _   
 |  _ \|  _ \|_ _/ ___||  \/  |  / \     |  _ \(_) | ___ | |_ 
 | |_) | |_) || |\___ \| |\/| | / _ \    | |_) | | |/ _ \| __|
 |  __/|  _ < | | ___) | |  | |/ ___ \   |  __/| | | (_) | |_ 
 |_|   |_| \_\___|____/|_|  |_/_/   \_\  |_|   |_|_|\___/ \__|
   Automated PRISMA Hyperspectral Data Acquisition Pipeline
=============================================================================
""")


def display_results_table(results: list[dict]):
    """Print results in a clean formatted ASCII table."""
    if not results:
        print("\n  [!] No acquisitions found matching your criteria.")
        return

    print(f"\nFound {len(results)} matching PRISMA acquisitions:\n")
    header = f"{'#':<3} | {'Product Clean ID':<46} | {'Acquisition Date':<20} | {'Cloud%':<6} | {'Size':<10}"
    print("-" * len(header))
    print(header)
    print("-" * len(header))

    for idx, r in enumerate(results, 1):
        clean_id = r["clean_id"]
        date_str = r["start_time"][:19].replace("T", " ") if r["start_time"] else "N/A"
        cloud = f"{r['cloud_cover']:.1f}%"
        size = format_size(r["data_size_bytes"]) if r["data_size_bytes"] else "N/A"
        print(f"{idx:<3} | {clean_id:<46} | {date_str:<20} | {cloud:<6} | {size:<10}")

    print("-" * len(header))


def display_orders_table(orders: list[dict]):
    """Print user orders in a clean formatted ASCII table."""
    if not orders:
        print("\n  [i] No past orders found for this user account.")
        return

    print(f"\nUser Order History ({len(orders)} total orders):\n")
    header = f"{'Order ID':<16} | {'Processor':<9} | {'Status':<11} | {'Acquisition Date':<20} | {'Production Date':<20}"
    print("-" * len(header))
    print(header)
    print("-" * len(header))

    for o in orders:
        order_id = o.get("externalOrderId", "N/A")
        proc = o.get("processorName", "N/A")
        status = o.get("status", "N/A")
        start = o.get("startTime", "N/A")
        prod_stop = o.get("productionStopTime", "N/A")
        print(f"{order_id:<16} | {proc:<9} | {status:<11} | {start:<20} | {prod_stop:<20}")

    print("-" * len(header))


def parse_args():
    parser = argparse.ArgumentParser(
        description="Automated PRISMA Data Acquisition Tool (GeoJSON & Bbox)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Search with bounding box [min_lon, min_lat, max_lon, max_lat]
  python download_prisma.py search --bbox 72.2 22.8 72.8 23.2 --max-cloud 20

  # Search with a GeoJSON file
  python download_prisma.py search --geojson sample_aoi.geojson --start-date 2021-01-01

  # Search using HTTP protocol instead of HTTPS
  python download_prisma.py search --bbox 72.2 22.8 72.8 23.2 --http

  # List existing user orders
  python download_prisma.py orders

  # Download a product directly
  python download_prisma.py download --id PRS_L1_STD_OFFL_20260130060212_20260130060216_0001 --output ./downloads

  # Full pipeline: Search AOI and automatically download best scene
  python download_prisma.py run --geojson sample_aoi.geojson --max-cloud 15 --download-first --output ./downloads
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Command: search
    search_parser = subparsers.add_parser("search", help="Search PRISMA catalog for matching AOI")
    _add_aoi_args(search_parser)
    _add_filter_args(search_parser)

    # Command: orders
    orders_parser = subparsers.add_parser("orders", help="List user processing orders and statuses")
    orders_parser.add_argument("--http", action="store_true", help="Try HTTP protocol instead of HTTPS")

    # Command: download
    dl_parser = subparsers.add_parser("download", help="Download a PRISMA product by ID or URL")
    dl_parser.add_argument("--id", "-i", dest="product_id", required=True, help="Product ID or direct URL")
    dl_parser.add_argument("--output", "-o", default="./downloads", help="Output directory (default: ./downloads)")
    dl_parser.add_argument("--no-extract", action="store_true", help="Do not extract .he5 from downloaded .zip")
    dl_parser.add_argument("--http", action="store_true", help="Try HTTP protocol instead of HTTPS")

    # Command: run (Default full pipeline)
    run_parser = subparsers.add_parser("run", help="Search AOI and download products")
    _add_aoi_args(run_parser)
    _add_filter_args(run_parser)
    run_parser.add_argument("--output", "-o", default="./downloads", help="Output directory (default: ./downloads)")
    run_parser.add_argument("--download-first", action="store_true", help="Automatically download the first (best) matching product")
    run_parser.add_argument("--download-all", action="store_true", help="Download all matching products")
    run_parser.add_argument("--order-if-needed", action="store_true", help="Submit processing order if scene is not yet processed")
    run_parser.add_argument("--processor", default="L2D", choices=["L1", "L2B", "L2C", "L2D"], help="Processor level for orders (default: L2D)")
    run_parser.add_argument("--no-extract", action="store_true", help="Do not extract .he5 from downloaded .zip")

    # Top-level fallback arguments if no subcommand given
    _add_aoi_args(parser)
    _add_filter_args(parser)
    parser.add_argument("--output", "-o", default="./downloads", help="Output directory (default: ./downloads)")
    parser.add_argument("--download-first", action="store_true", help="Automatically download the first (best) matching product")
    parser.add_argument("--download-all", action="store_true", help="Download all matching products")

    return parser.parse_args()


def _add_aoi_args(p: argparse.ArgumentParser):
    group = p.add_argument_group("Area of Interest (AOI)")
    group.add_argument("--geojson", "-g", help="Path to GeoJSON file or GeoJSON string")
    group.add_argument(
        "--bbox", "-b", nargs=4, type=float, metavar=("MIN_LON", "MIN_LAT", "MAX_LON", "MAX_LAT"),
        help="Bounding box coordinates in WGS84: min_lon min_lat max_lon max_lat"
    )
    group.add_argument("--aoi", help="Flexible AOI: GeoJSON path, JSON string, or 'min_lon,min_lat,max_lon,max_lat'")


def _add_filter_args(p: argparse.ArgumentParser):
    group = p.add_argument_group("Search & Filter Options")
    group.add_argument("--start-date", "-s", help="Start acquisition date (e.g. 2021-01-01 or ISO format)")
    group.add_argument("--end-date", "-e", help="End acquisition date (e.g. 2026-12-31)")
    group.add_argument("--max-cloud", "-c", type=float, default=30.0, help="Maximum cloud coverage percentage (default: 30%%)")
    group.add_argument("--limit", "-l", type=int, default=20, help="Max results to fetch (default: 20)")
    group.add_argument("--http", action="store_true", help="Try HTTP protocol instead of HTTPS as well")


def main():
    print_banner()
    args = parse_args()

    command = args.command
    if not command:
        if hasattr(args, "product_id") and args.product_id:
            command = "download"
        elif args.geojson or args.bbox or args.aoi:
            command = "run"
        else:
            command = "search"

    # Verify credentials
    if not config.has_credentials:
        print("[!] Error: PRISMA credentials not found.")
        print("    Please set PRISMA_USER / PRISMA_PASS in .env or environment.")
        sys.exit(1)

    print(f"[*] Account: {config.username}")
    print(f"[*] Session cache: {SESSION_FILE}")

    # Authenticate
    session = get_authenticated_session()

    # 1. Handle Orders Command
    if command == "orders":
        print("[*] Fetching user order history...")
        orders = get_user_orders(session=session, use_http=args.http)
        display_orders_table(orders)
        return

    # 2. Handle Direct Download Command
    if command == "download":
        product_id = getattr(args, "product_id", None)
        if not product_id:
            print("[!] Error: Must specify --id <product_id_or_url>")
            sys.exit(1)
        extract = not getattr(args, "no_extract", False)
        print(f"[*] Downloading product: {product_id} to {args.output}...")
        try:
            res = download_product(
                product_id,
                output_dir=args.output,
                session=session,
                use_http=args.http,
                extract=extract,
            )
            print("\n[+] Download completed successfully!")
            print(f"    ZIP Archive: {res.get('zip_path')}")
            if res.get("he5_path"):
                print(f"    Extracted HDF5: {res.get('he5_path')}")
            print(f"    Total Size: {format_size(res.get('file_size_bytes', 0))}")
        except Exception as e:
            print(f"\n[-] Download error: {e}")
            sys.exit(1)
        return

    # 3. Handle Search and Run Commands
    target_aoi = getattr(args, "aoi", None) or getattr(args, "geojson", None) or getattr(args, "bbox", None)
    if not target_aoi:
        # Prompt user or default to sample_aoi.geojson if present
        sample_p = Path("sample_aoi.geojson")
        if sample_p.is_file():
            print(f"[*] No AOI specified. Defaulting to sample AOI: {sample_p.resolve()}")
            target_aoi = sample_p
        else:
            print("[!] Error: Please provide an AOI via --geojson <file> or --bbox <min_lon> <min_lat> <max_lon> <max_lat>")
            sys.exit(1)

    parsed_aoi = parse_aoi(target_aoi)
    print(f"[*] Parsed AOI: bbox=[{parsed_aoi.min_lon:.4f}, {parsed_aoi.min_lat:.4f}, {parsed_aoi.max_lon:.4f}, {parsed_aoi.max_lat:.4f}]")

    print("[*] Searching PRISMA Catalog...")
    results = search_prisma(
        aoi=parsed_aoi,
        start_date=args.start_date,
        end_date=args.end_date,
        max_cloud=args.max_cloud,
        rows=args.limit,
        session=session,
        use_http=args.http,
    )

    display_results_table(results)

    # Check if user wanted to download matching results
    should_download = getattr(args, "download_first", False) or getattr(args, "download_all", False)
    if should_download and results:
        items_to_download = results if args.download_all else [results[0]]
        print(f"\n[*] Proceeding to download {len(items_to_download)} acquisition(s)...")

        # Check existing user orders to find ready downloads
        orders = get_user_orders(session=session, use_http=args.http)
        completed_orders = {
            o.get("startTime", "")[:19]: o for o in orders if o.get("status") == "COMPLETED"
        }

        out_dir = Path(args.output)
        out_dir.mkdir(parents=True, exist_ok=True)
        extract = not getattr(args, "no_extract", False)

        for item in items_to_download:
            clean_id = item["clean_id"]
            start_key = item["start_time"][:19].replace("T", " ")
            print(f"\n--> Processing Acquisition: {clean_id} ({item['start_time']})")

            # Check if order is already completed
            if start_key in completed_orders:
                ord_info = completed_orders[start_key]
                proc = ord_info.get("processorName", "L2D")
                print(f"    [i] Matching processed order found: {ord_info.get('externalOrderId')} (Level: {proc})")

            # Attempt download
            try:
                res = download_product(
                    clean_id,
                    output_dir=out_dir,
                    session=session,
                    use_http=args.http,
                    extract=extract,
                )
                print(f"    [+] Successfully acquired: {res.get('zip_path')}")
                if res.get("he5_path"):
                    print(f"    [+] HDF5 Data Cube: {res.get('he5_path')}")
            except Exception as e:
                print(f"    [-] Direct download notice: {e}")
                if getattr(args, "order_if_needed", False):
                    proc = getattr(args, "processor", "L2D")
                    print(f"    [*] Submitting processing order for Level {proc}...")
                    try:
                        order_res = order_processing(clean_id, processor=proc, session=session, use_http=args.http)
                        print(f"    [+] Order submitted: {order_res}")
                    except Exception as order_err:
                        print(f"    [-] Order submission error: {order_err}")
                else:
                    print("    [!] Tip: If this Level 0 scene is not yet packaged, run with --order-if-needed to submit a processing order.")


if __name__ == "__main__":
    main()
