"""
Unit tests for AOI parsing (GeoJSON and Bounding Box).
"""

import pytest
from prisma_pilot.search import parse_aoi, AOI


def test_parse_bbox_list():
    aoi = parse_aoi([72.2, 22.8, 72.8, 23.2])
    assert isinstance(aoi, AOI)
    assert aoi.min_lon == 72.2
    assert aoi.min_lat == 22.8
    assert aoi.max_lon == 72.8
    assert aoi.max_lat == 23.2
    assert "POLYGON" in aoi.wkt


def test_parse_bbox_string():
    aoi = parse_aoi("72.2, 22.8, 72.8, 23.2")
    assert isinstance(aoi, AOI)
    assert aoi.min_lon == 72.2
    assert aoi.max_lat == 23.2


def test_parse_geojson_dict():
    geojson_polygon = {
        "type": "Polygon",
        "coordinates": [
            [
                [72.2, 22.8],
                [72.8, 22.8],
                [72.8, 23.2],
                [72.2, 23.2],
                [72.2, 22.8],
            ]
        ],
    }
    aoi = parse_aoi(geojson_polygon)
    assert isinstance(aoi, AOI)
    assert aoi.min_lon == pytest.approx(72.2)
    assert aoi.max_lon == pytest.approx(72.8)


def test_parse_feature_collection():
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [72.25, 22.85],
                            [72.75, 22.85],
                            [72.75, 23.15],
                            [72.25, 23.15],
                            [72.25, 22.85],
                        ]
                    ],
                },
                "properties": {},
            }
        ],
    }
    aoi = parse_aoi(fc)
    assert isinstance(aoi, AOI)
    assert aoi.min_lon == pytest.approx(72.25)
    assert aoi.max_lat == pytest.approx(23.15)


def test_parse_invalid():
    with pytest.raises(ValueError):
        parse_aoi("invalid_string_not_coords")
