from pathlib import Path

from osm import parse_md5, snapshot
from family import PROJECTS


def test_snapshot_names():
    assert snapshot("india-261025.osm.pbf") == {"region": "india", "date": "2026-10-25", "format": "osm.pbf"}
    assert snapshot("north-eastern-zone-261025-free.gpkg.zip") == {"region": "north-eastern-zone", "date": "2026-10-25",
                                                                   "format": "gpkg.zip"}
    assert snapshot("india-latest.osm.pbf") is None
    assert snapshot("india-261025.osm.pbf.md5") is None


def test_md5_file():
    text = "0987260dd817f9f73a122d1eeadb952c  india-261025.osm.pbf\n"
    assert parse_md5(text, "india-261025.osm.pbf") == "0987260dd817f9f73a122d1eeadb952c"
    assert parse_md5(text, "india-261024.osm.pbf") is None
    assert parse_md5("<html>404</html>", "india-261025.osm.pbf") is None


def test_queue():
    items = PROJECTS[0]["items"]
    assert len(items) == 13 and len({i["key"] for i in items}) == 13
    assert all(i["payload"]["url"].startswith("https://download.geofabrik.de/asia/") for i in items)


def test_bhuvan_capabilities():
    import bhuvan
    rows = bhuvan.parse((Path(__file__).parent / "pages" / "bhuvan-capabilities-world.xml").read_bytes())
    ids = [rid for rid, _ in rows]
    assert len(ids) == 12 and len(set(ids)) == 12 and "world:world_base" in ids
    data = dict(rows)["world:world_base"]
    assert data["workspace"] == "world" and data["styles"] and data["styles"][0]["legend_url"].startswith("https://")
    assert all(d["bbox"] is None or (d["bbox"][0] <= d["bbox"][2] and d["bbox"][1] <= d["bbox"][3]) for _, d in rows)


def test_bhuvan_queue():
    names = [p["name"] for p in PROJECTS]
    assert names == ["reference-geography-osm-india", "reference-geography-bhuvan-vec1", "reference-geography-bhuvan-vec2"]
