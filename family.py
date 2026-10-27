"""What this family scrapes. Change this file first.

FAMILY must equal the repo name (s1d-labs/<FAMILY>) and the family the hub owner added on scrape.s1d.me/runners.
Each project is one queue of work on one site; `target` is the host it hits (the hub caps workers per target).
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

FAMILY = json.loads((Path(__file__).parent / "scrape.json").read_text())["family"]

# OpenStreetMap India from Geofabrik: the whole country as .osm.pbf, and each of its six zones as .osm.pbf and GeoPackage.
# Geofabrik rebuilds them daily; `*-latest*` redirects to the dated file (india-latest.osm.pbf -> india-261025.osm.pbf).
# One snapshot is about 7.5 GB, so we keep one a month: the setup workflow runs monthly and seeds that month's items.
GEOFABRIK = "https://download.geofabrik.de/asia"
ZONES = ["north-eastern", "western", "northern", "eastern", "central", "southern"]     # smallest first


def osm_india_files():
    """[(key, path under GEOFABRIK)], small files first so scrape-check's few items stay quick."""
    files = [(f"{z}-zone.osm.pbf", f"india/{z}-zone-latest.osm.pbf") for z in ZONES]
    files.append(("india.osm.pbf", "india-latest.osm.pbf"))
    files += [(f"{z}-zone.gpkg.zip", f"india/{z}-zone-latest-free.gpkg.zip") for z in ZONES]
    return files


MONTH = os.environ.get("OSM_MONTH") or datetime.now(timezone.utc).strftime("%Y-%m")

PROJECTS = [
    {
        "name": f"{FAMILY}-osm-india",          # project names: 2-64 chars of a-z 0-9 - _, start them with the family name
        "title": "OpenStreetMap India extracts (Geofabrik)",
        "task": "osm",                           # a task from scrape.json
        "target": "download.geofabrik.de",
        "env": {"GEOFABRIK": GEOFABRIK},
        "probe": f"{FAMILY}:download.geofabrik.de",
        "max_workers": 2,                        # Geofabrik is one donated server: two big downloads at a time is plenty
        "unit_label": "file", "record_label": "file",
        # the queue: one item per file per month; the task stores the dated file Geofabrik's `latest` points to
        "items": [{"key": f"{MONTH}/{key}", "payload": {"url": f"{GEOFABRIK}/{path}", "expected": 1}}
                  for key, path in osm_india_files()],
    },
]

# Bhuvan (ISRO's geoportal): the catalogue of layers its two vector GeoServers publish over WMS, one project per server so the
# hub's per-host limits and health checks match. Monthly, like OSM India: a refresh that just updates each layer's record.
BHUVAN = {"vec1": 6700, "vec2": 4600}       # server -> layers it lists (about; for progress on the dashboard)
# health check: a 1 KB legend image of a layer both servers publish (their capabilities are 220 KB even when empty)
BHUVAN_PROBE = "https://bhuvan-{s}.nrsc.gov.in/bhuvan/ows?service=WMS&version=1.3.0&request=GetLegendGraphic&format=image%2Fpng&width=20&height=20&layer=moef%3Abiosphere"

PROJECTS += [
    {
        "name": f"{FAMILY}-bhuvan-{s}",
        "title": f"Bhuvan WMS layer catalogue (bhuvan-{s})",
        "task": "bhuvan",
        "target": f"bhuvan-{s}.nrsc.gov.in",
        "env": {},
        "probe": f"{FAMILY}:bhuvan-{s}.nrsc.gov.in",
        "max_workers": 1,
        "unit_label": "catalogue", "record_label": "layer",
        "items": [{"key": f"{MONTH}/capabilities", "payload": {
            "url": f"https://bhuvan-{s}.nrsc.gov.in/bhuvan/wms?service=WMS&version=1.3.0&request=GetCapabilities", "expected": n}}],
    }
    for s, n in BHUVAN.items()
]

# health checks the hub runs every minute; work for a project holds while its probe fails
PROBES = [{"name": f"{FAMILY}:download.geofabrik.de", "url": f"{GEOFABRIK}/india.html", "expect": "india-latest.osm.pbf"}] + [
    {"name": f"{FAMILY}:bhuvan-{s}.nrsc.gov.in", "url": BHUVAN_PROBE.format(s=s), "expect": "PNG"} for s in BHUVAN]
