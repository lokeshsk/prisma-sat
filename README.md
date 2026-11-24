# prisma-sat: PRISMA Hyperspectral Data Acquisition Pipeline

An automated Python toolkit and CLI to search, order, and download Italian Space Agency (**ASI PRISMA**) hyperspectral satellite data for any Area of Interest (AOI) provided in **GeoJSON** or **Bounding Box (bbox)** format.

---

## Table of Contents

1. [Understanding PRISMA vs. Sentinel Data Model](#1-understanding-prisma-vs-sentinel-data-model)
2. [Prerequisites & Environment](#2-prerequisites--environment)
3. [Credentials Setup (.env)](#3-credentials-setup-env)
4. [Step-by-Step Workflow (In Order of Use)](#4-step-by-step-workflow-in-order-of-use)
   - [Step 1: Check Completed Orders](#step-1-check-completed-orders)
   - [Step 2: Search PRISMA Catalog by Bounding Box](#step-2-search-prisma-catalog-by-bounding-box)
   - [Step 3: Search PRISMA Catalog by GeoJSON](#step-3-search-prisma-catalog-by-geojson)
   - [Step 4: Search Using HTTP Protocol Fallback](#step-4-search-using-http-protocol-fallback)
   - [Step 5: Submit a Processing Order for Raw Scenes](#step-5-submit-a-processing-order-for-raw-scenes)
   - [Step 6: Download Completed Products](#step-6-download-completed-products)
5. [Complete CLI Command Reference](#5-complete-cli-command-reference)
6. [Python API / SDK Usage](#6-python-api--sdk-usage)
7. [Product Levels & HDF5 Data Cube Structure](#7-product-levels--hdf5-data-cube-structure)
8. [Troubleshooting & FAQ](#8-troubleshooting--faq)

---

## 1. Understanding PRISMA vs. Sentinel Data Model

Unlike Sentinel-2 (which systematically pre-processes the globe and hosts instant-download GeoTIFFs), **PRISMA operates on an On-Demand Processing model**:

- **Catalog searches return Level 0 (`PRS_L0__EO`)**: The catalog indexes all raw satellite passes.
- **Processing is on-demand**: To get analysis-ready data (e.g., Level-2D geocoded surface reflectance), an order must be submitted to ASI's HPC processing cluster.
- **Turnaround time**: Processing takes between **20 to 45 minutes** depending on cluster load.
- **Direct download**: A product can only be downloaded immediately if it was already processed in your account history (or once a newly submitted order reaches `COMPLETED` status).

---

## 2. Prerequisites & Environment

The project runs using Python 3.10+ and Google Chrome (for automated headless OAuth2 SSO authentication):

```bash
cd /home/ubuntu/Documents/prisma_pilot
```

The dedicated virtual environment is already prepared at `.venv/`:
- **Python interpreter:** `./.venv/bin/python`
- **Dependencies installed:** `requests`, `python-dotenv`, `websockets`, `h5py`, `rasterio`, `shapely`, `numpy`.

---

## 3. Credentials Setup (.env)

Ensure your PRISMA portal credentials are in a `.env` file in the project root:

```env
PRISMA_USER=your_username
PRISMA_PASS=your_password
```

*(The loader also accepts `PRISMA_USERNAME` and `PRISMA_PASSWORD`)*

On the first run, the tool uses headless Chrome via DevTools Protocol (CDP) to log in to the WSO2 Identity Server, approve OAuth consent, and cache the session cookies at `~/.cache/prisma_pilot/session.json`. Subsequent runs execute in **~2 seconds** without opening a browser.

---

## 4. Step-by-Step Workflow (In Order of Use)

### Step 1: Check Completed Orders

Before requesting new processing, check if any scenes over your target area have already been processed and are ready for immediate download:

```bash
./.venv/bin/python download_prisma.py orders
```

**Output:**
```
User Order History (8 total orders):
----------------------------------------------------------------------------------------
Order ID         | Processor | Status      | Acquisition Date     | Production Date     
----------------------------------------------------------------------------------------
extref_162267    | L2C       | COMPLETED   | 2025-10-06 06:02:00  | 2026-11-23 07:56:15 
extref_162264    | L2C       | COMPLETED   | 2026-11-10 05:58:39  | 2026-11-23 04:49:50 
extref_162010    | L2D       | COMPLETED   | 2026-09-07 05:55:28  | 2026-11-20 04:58:20 
extref_162009    | L2D       | COMPLETED   | 2026-11-10 05:58:43  | 2026-11-20 04:57:29 
extref_161673    | L1_A_EO   | COMPLETED   | 2026-01-30 06:02:12  | 2026-11-18 09:27:50 
----------------------------------------------------------------------------------------
```

---

### Step 2: Search PRISMA Catalog by Bounding Box

Search for scenes intersecting a bounding box `[min_lon, min_lat, max_lon, max_lat]` in WGS84:

```bash
# Search with max 20% cloud cover
./.venv/bin/python download_prisma.py search \
  --bbox 72.2 22.8 72.8 23.2 \
  --max-cloud 20 \
  --limit 10
```

**With date filtering:**
```bash
./.venv/bin/python download_prisma.py search \
  --bbox 72.2 22.8 72.8 23.2 \
  --start-date 2023-01-01 \
  --end-date 2026-12-31 \
  --max-cloud 10
```

---

### Step 3: Search PRISMA Catalog by GeoJSON

Search using a GeoJSON file containing a polygon or feature collection:

```bash
./.venv/bin/python download_prisma.py search \
  --geojson sample_aoi.geojson \
  --max-cloud 15 \
  --limit 10
```

---

### Step 4: Search Using HTTP Protocol Fallback

To test using `http://` endpoints first (with automatic, seamless fallback to `https://` if the server demands TLS):

```bash
./.venv/bin/python download_prisma.py search \
  --bbox 72.2 22.8 72.8 23.2 \
  --http \
  --max-cloud 20
```

*The script tries `http://` first, detects that PRISMA requires TLS for authenticated queries, preserves your session cookies, and completes over `https://`.*

---

### Step 5: Submit a Processing Order for Raw Scenes

If a scene is not yet processed, trigger a processing order for Level 2D (orthorectified surface reflectance):

```bash
./.venv/bin/python download_prisma.py run \
  --geojson sample_aoi.geojson \
  --max-cloud 10 \
  --processor L2D \
  --order-if-needed
```

Once submitted, monitor progress with `./.venv/bin/python download_prisma.py orders` until status is `COMPLETED` (~20–45 min).

---

### Step 6: Download Completed Products

Download a product package by clean ID or direct URL:

```bash
# Download by product ID and extract the HDF5 (.he5) data cube
./.venv/bin/python download_prisma.py download \
  --id PRS_L1_STD_OFFL_20260130060212_20260130060216_0001 \
  --output ./downloads
```

**Options:**
- `--output ./my_dir`: Custom download folder (defaults to `./downloads`).
- `--no-extract`: Keep only the `.zip` archive without unpacking `.he5`.
- `--http`: Attempt download over HTTP protocol first.

---

## 5. Complete CLI Command Reference

### Synopsis
```text
download_prisma.py [-h] [--output OUTPUT] [--http] {search,orders,download,run} ...
```

### Commands

| Subcommand | Purpose | Key Arguments |
| :--- | :--- | :--- |
| `search` | Discover acquisitions intersecting AOI | `--bbox`, `--geojson`, `--max-cloud`, `--start-date`, `--end-date`, `--limit`, `--http` |
| `orders` | List account order history & status | `--http` |
| `download` | Download specific product file | `--id <id_or_url>`, `--output`, `--no-extract`, `--http` |
| `run` | Search AOI and download best match | `--bbox` / `--geojson`, `--download-first`, `--order-if-needed`, `--processor` |

### Parameter Details

- `--bbox MIN_LON MIN_LAT MAX_LON MAX_LAT`: Four coordinates in decimal degrees (WGS84).
- `--geojson PATH`: Path to a `.geojson` or `.json` file.
- `--max-cloud FLOAT`: Maximum cloud coverage percentage (e.g. `20` for $\le 20\%$).
- `--start-date YYYY-MM-DD`: Earliest acquisition timestamp.
- `--end-date YYYY-MM-DD`: Latest acquisition timestamp.
- `--limit INT`: Maximum number of acquisitions to display.
- `--processor {L1, L2B, L2C, L2D}`: Target processing level (default: `L2D`).
- `--http`: Attempt HTTP protocol first with intelligent HTTPS fallback.
- `--no-extract`: Disable automatic extraction of `.he5` files from downloaded `.zip`.

---

## 6. Python API / SDK Usage

You can also import and use the pipeline directly in your Python code:

```python
from prisma_pilot import parse_aoi, search_prisma, get_user_orders, download_product

# 1. Parse AOI from Bounding Box or GeoJSON
aoi = parse_aoi([72.2, 22.8, 72.8, 23.2])
# or: aoi = parse_aoi("sample_aoi.geojson")

# 2. Search PRISMA Catalog
scenes = search_prisma(
    aoi=aoi,
    max_cloud=15.0,
    start_date="2022-01-01",
    use_http=True  # Tries HTTP first with automatic HTTPS fallback
)

print(f"Found {len(scenes)} matching acquisitions:")
for s in scenes[:5]:
    print(f"  {s['clean_id']} | Date: {s['start_time']} | Cloud: {s['cloud_cover']}%")

# 3. Check Order History
orders = get_user_orders()
for o in orders:
    print(f"  Order: {o['externalOrderId']} | Level: {o['processorName']} | Status: {o['status']}")

# 4. Download a Product
result = download_product(
    product_id_or_url="PRS_L1_STD_OFFL_20260130060212_20260130060216_0001",
    output_dir="./downloads",
    extract=True  # Automatically unpacks .he5
)
print("Downloaded:", result["zip_path"])
print("HDF5 Cube:", result["he5_path"])
```

---

## 7. Product Levels & HDF5 Data Cube Structure

### Processing Levels

- **`PRS_L0__EO`**: Raw satellite telemetry (stored in archive).
- **`L1_A_EO`**: Top-Of-Atmosphere (TOA) calibrated radiance.
- **`L2B`**: Ground surface reflectance and atmospheric parameters.
- **`L2C`**: Bottom-Of-Atmosphere (BOA) surface reflectance (standard geometry).
- **`L2D`**: Geocoded Bottom-Of-Atmosphere surface reflectance orthorectified with DEM (recommended).

### Structure of Extracted `.he5`

The extracted HDF-EOS5 file contains three co-registered cubes:

```text
HDFEOS/SWATHS/
├── PRS_L1_HRC (Panchromatic Camera)
│   └── 5-meter spatial resolution (6000 x 6000 pixels)
├── PRS_L1_HCO (Hyperspectral SWIR)
│   └── 173 spectral bands (943 nm to 2497 nm, 30m resolution)
└── PRS_L1_HCO (Hyperspectral VNIR)
    └── 66 spectral bands (406 nm to 977 nm, 30m resolution)
```

---

## 8. Troubleshooting & FAQ

### Q: Why does the catalog return `PRS_L0__EO` instead of L2D?
> PRISMA archives data at Level 0. To get Level 1, 2C, or 2D, submit an order with `--order-if-needed --processor L2D`. Processing takes 20–45 minutes.

### Q: How long is the login session valid?
> Session tokens are cached in `~/.cache/prisma_pilot/session.json`. If expired, the tool automatically re-authenticates via headless Chrome CDP in the background.

### Q: What happens when using `--http`?
> The tool explicitly attempts `http://prisma.asi.it`. The ASI Apache server rejects unencrypted HTTP requests for authenticated endpoints with HTTP 401. The tool detects this, protects your session cookies from corruption, logs the fallback, and completes over HTTPS.
