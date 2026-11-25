from __future__ import annotations

import pytest
from prisma_pilot.cli import parse_args
import prisma_sat


def test_prisma_sat_import():
    assert hasattr(prisma_sat, "search_prisma")
    assert hasattr(prisma_sat, "download_product")
    assert hasattr(prisma_sat, "parse_aoi")
    assert prisma_sat.__version__ == "0.1.0"


def test_cli_parse_bbox():
    args = parse_args(["search", "--bbox", "10.0", "45.0", "11.0", "46.0", "--limit", "5"])
    assert args.command == "search"
    assert args.bbox == [10.0, 45.0, 11.0, 46.0]
    assert args.limit == 5


def test_cli_parse_download():
    args = parse_args(["download", "--id", "PRS_L1_TEST_001", "--output", "./output_test", "--http"])
    assert args.command == "download"
    assert args.product_id == "PRS_L1_TEST_001"
    assert args.output == "./output_test"
    assert args.http is True


def test_cli_parse_orders():
    args = parse_args(["orders"])
    assert args.command == "orders"


def test_cli_parse_order_command():
    args = parse_args(["order", "--id", "PRS_L0__EO_OFFL_20210316055214_20210316055218_0001", "--processor", "L2D"])
    assert args.command == "order"
    assert args.product_id == "PRS_L0__EO_OFFL_20210316055214_20210316055218_0001"
    assert args.processor == "L2D"


def test_extref_order_id_notice():
    from prisma_pilot.downloader import download_product
    with pytest.raises(ValueError, match="is an Order Reference ID, not a download URL"):
        download_product("extref_160770")


def test_prs_l0_direct_download_notice():
    from prisma_pilot.downloader import download_product
    with pytest.raises(ValueError, match="is a raw Level 0 catalog acquisition"):
        download_product("PRS_L0__EO_OFFL_20210316055214_20210316055218_0001")

