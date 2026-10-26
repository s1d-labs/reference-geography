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

# health checks the hub runs every minute; work for a project holds while its probe fails
PROBES = [{"name": f"{FAMILY}:download.geofabrik.de", "url": f"{GEOFABRIK}/india.html", "expect": "india-latest.osm.pbf"}]
