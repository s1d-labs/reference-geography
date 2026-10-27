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
    assert names[:3] == ["reference-geography-osm-india", "reference-geography-bhuvan-vec1", "reference-geography-bhuvan-vec2"]


def test_datameet_inventory():
    import tarfile
    from datameet import inventory, records
    with tarfile.open(Path(__file__).parent / "pages" / "datameet-Pune_wards-0eb4fc7.tar.gz") as tar:
        sha, when, files = inventory(tar)
    assert sha == "0eb4fc7568cd6fd67dc63ca7da3426fe86af6b0a" and when.startswith("2015-08-25")
    assert ("GeoData/pune-admin-wards.geojson", 297307) in files and len(files) == 6
    rows = records("Pune_wards", sha, when, files)
    assert rows[0][0] == "Pune_wards" and rows[0][1]["files"] == 6 and rows[0][1]["readme"] == "Readme.md"
    assert dict(rows)["Pune_wards/CSVs/pune-wards-info.csv"]["ext"] == "csv"
    assert len({rid for rid, _ in rows}) == len(rows)


def test_datameet_project():
    p = next(p for p in PROJECTS if p["name"] == "reference-geography-datameet")
    assert callable(p["items"]) and p["target"] == "codeload.github.com"
