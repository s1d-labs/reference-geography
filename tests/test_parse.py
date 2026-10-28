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


def test_copernicus_records():
    import json
    from copernicus import record
    page = json.loads((Path(__file__).parent / "pages" / "copernicus-s2-page.json").read_text())
    rid, data = record(page["value"][0])
    assert rid == "00044e9f-86b5-4e31-92dd-a8245ba108e6"
    assert data["collection"] == "SENTINEL-2" and data["product_type"] == "S2MSI1C" and data["bytes"] == 315814667
    assert data["md5"] == "3c02345894b36288d9f27d1b036f05a7" and data["attributes"]["tileId"] == "43NEJ"
    assert "sourceProduct" not in data["attributes"]                   # long values are left out
    assert data["footprint"]["coordinates"][0][0] == [75.4913, 7.1483]


def test_copernicus_queue():
    from datetime import datetime, timezone
    from urllib.parse import parse_qs, urlparse
    from copernicus import month_window, query_url
    from family import months
    assert months("2025-11", "2026-02") == ["2025-11", "2025-12", "2026-01"]
    assert month_window("2025-12") == (datetime(2025, 12, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc))
    q = parse_qs(urlparse(query_url("SENTINEL-1", *month_window("2025-09"), 0)).query)
    assert q["$count"] == ["true"] and "ContentDate/Start lt 2025-10-01T00:00:00.000000Z" in q["$filter"][0]
    p = next(p for p in PROJECTS if p["name"] == "reference-geography-copernicus")
    assert p["items"][0]["key"] == "SENTINEL-1/2014-10" and len({i["key"] for i in p["items"]}) == len(p["items"])


def test_bhuvan_thematic_pages():
    from bhuvan_thematic import parse
    page = lambda n: (Path(__file__).parent / "pages" / f"bhuvan-stats-{n}.html").read_text(errors="replace")
    s = parse(page("lulc503-state"))
    assert (s["period"], s["place"], s["total"], s["unit"]) == ("2015-2016", "Andhra Pradesh", 162989.0, "Sq.Km")
    assert s["rows"][0] == {"class": "Builtup,Urban", "values": [1725.19]} and len(s["rows"]) == 22
    d = parse(page("lulc-dist"))
    assert d["place"] == "Anantapur" and d["rows"][-1] == {"class": "Total", "values": [19130.0]}
    f = parse(page("fldhz-state"))
    assert f["rows"][0] == {"class": "Very High", "values": [128687.0, 1.64, 5.79]}       # Indian digit grouping: 1,28,687
    k = parse(page("lulc250-in-kharif"))
    assert k["period"] == "2023-24" and k["rows"][0]["class"] == "ANDAMAN AND NICOBAR" and k["total_unit"] == "L ha"
    assert parse(page("ld0506-dist-empty")) is None


def test_bhuvan_thematic_queue():
    from bhuvan_thematic import districts, doc_paths
    assert districts("<option>Select<option value='2822_MULTIPOLYGON(((77.6 15.1, 77.7 15.2)))'>Anantapur") == [("2822", "Anantapur")]
    assert "LULC/MAP/Stat/AP.pdf" in doc_paths("lulc") and "wl1516/Wasteland_Atlas_2019_Full_opt.pdf" in doc_paths("wl1516")
    p = next(p for p in PROJECTS if p["name"] == "reference-geography-bhuvan-thematic")
    keys = [i["key"] for i in p["items"]]
    assert keys[0] == "stats/fldhz/AS" and len(keys) == len(set(keys)) == 312


def test_census_helpers():
    from census import download_links, safe
    page = ('<a href="https://censusindia.gov.in/nada/index.php/catalog/32977/download/36796/38875_1991_PRO.pdf">PDF</a>'
            '<a href="https://censusindia.gov.in/nada/index.php/catalog/32977/download/36796/38875_1991_PRO.pdf">again</a>'
            '<a href="https://censusindia.gov.in/nada/index.php/catalog/43368/download/47071/35%20A-2%20Andaman%20%20Nicobar.xlsx">x</a>')
    assert download_links(page) == [("32977", "36796", "38875_1991_PRO.pdf"), ("43368", "47071", "35 A-2 Andaman  Nicobar.xlsx")]
    assert safe("35 A-2 Andaman  Nicobar Islands.xlsx") == "35_A-2_Andaman_Nicobar_Islands.xlsx"
    assert safe("जनगणना.pdf") == ".pdf"           # hence the download id in front of every stored name
    p = next(p for p in PROJECTS if p["name"] == "reference-geography-census")
    assert callable(p["items"]) and p["target"] == "censusindia.gov.in"
