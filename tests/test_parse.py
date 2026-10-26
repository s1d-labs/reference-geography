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
