"""The family's `copernicus` task (see scrape.json): the catalogue of Sentinel products over India from the Copernicus Data
Space Ecosystem (dataspace.copernicus.eu). Metadata only: downloading the products needs a CDSE account and runs to petabytes.
Try it without the hub: python copernicus.py --local [collection] [YYYY-MM]   (counts and prints the first products)

Each queue item is one collection for one month. Its public OData catalogue pages at most 1,000 products and skips at most 10,000,
so we count the month first and halve the time window until every piece fits, then page it in a fixed order. One record per
product, id = CDSE's product Id; the month's products also go to the bucket as <project>/<collection>/<YYYY-MM>.jsonl.gz.
"""
import gzip
import json
import os
import sys
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlencode

import requests

from common import LocalHub, request

PROJECT = os.environ.get("SCRAPE_POOL_PROJECT", "")
DEADLINE = time.time() + float(os.environ.get("SCRAPE_MAX_HOURS", "1")) * 3600 - 120
CATALOGUE = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
PAGE, MAX_SKIP = 1000, 10000                # the catalogue's limits for $top and $skip
TIMEOUT = (30, 180)
# India's outline: Geofabrik's india.poly buffered by 0.3° and simplified to 71 points; it contains the whole extract with
# about 8% to spare, unlike a bounding box, which takes in much of Pakistan, Nepal, Bangladesh and Myanmar
INDIA = ("POLYGON((70.7 24.71,69.17 26.63,69.23 27.37,70.22 28.32,72.71 29.28,74.2 31.18,74.54 32.22,73.69 33.14,73.44 34.35,"
         "73.73 34.88,76.12 34.99,76.59 35.2,76.42 35.62,76.79 36.03,78.33 35.81,78.6 34.94,79.39 34.55,79.15 33.7,79.79 32.67,"
         "79.13 31.79,81.36 30.27,80.54 29.0,83.09 27.76,84.2 27.82,85.39 27.1,87.59 26.72,87.86 26.79,87.83 28.11,88.67 28.48,"
         "89.21 28.16,89.25 27.15,91.62 27.13,91.24 27.58,91.44 28.12,92.34 28.2,94.56 29.63,96.35 29.61,97.65 28.34,97.49 27.03,"
         "96.25 26.94,95.45 26.37,94.99 24.77,94.35 23.6,93.76 23.58,93.49 22.14,93.04 21.66,92.41 21.74,92.07 22.88,91.47 22.66,"
         "90.87 23.49,90.99 24.1,91.93 24.85,89.72 25.01,89.53 25.66,88.53 25.98,89.3 25.39,88.59 24.68,89.06 24.38,90.73 17.11,"
         "93.3 14.17,95.82 13.42,94.61 5.72,82.17 9.43,80.52 10.36,79.85 9.52,79.76 8.7,78.48 7.21,71.93 7.28,67.38 23.78,"
         "68.71 24.67,70.7 24.71))")


def _iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def query_url(collection, start, end, top, skip=0):
    """The catalogue URL for `collection` products over India sensed in [start, end), in a fixed order. Pure."""
    f = (f"Collection/Name eq '{collection}' and OData.CSC.Intersects(area=geography'SRID=4326;{INDIA}') "
         f"and ContentDate/Start ge {_iso(start)} and ContentDate/Start lt {_iso(end)}")
    q = {"$filter": f, "$top": top, "$skip": skip, "$orderby": "ContentDate/Start asc,Id asc"}
    if top:
        q["$expand"] = "Attributes"
    else:
        q["$count"] = "true"
    return f"{CATALOGUE}?{urlencode(q, quote_via=quote)}"


def _round(c):
    return [_round(x) for x in c] if isinstance(c, list) else round(c, 4)


def record(p):
    """(record id, data) for one catalogue product (dict from the OData answer). Pure."""
    attrs = {a["Name"]: a["Value"] for a in p.get("Attributes") or []
             if isinstance(a.get("Value"), (int, float, bool)) or (isinstance(a.get("Value"), str) and len(a["Value"]) <= 100)}
    geo = p.get("GeoFootprint")
    md5 = next((c["Value"] for c in p.get("Checksum") or [] if c.get("Algorithm") == "MD5"), None)
    return p["Id"], {
        "name": p["Name"],
        "collection": attrs.pop("platformShortName", None),
        "product_type": attrs.pop("productType", None),
        "start": (p.get("ContentDate") or {}).get("Start"),
        "end": (p.get("ContentDate") or {}).get("End"),
        "published": p.get("PublicationDate"),
        "modified": p.get("ModificationDate"),
        "online": p.get("Online"),
        "bytes": p.get("ContentLength"),
        "md5": md5,
        "s3_path": p.get("S3Path"),
        "footprint": {"type": geo["type"], "coordinates": _round(geo["coordinates"])} if geo else None,
        "attributes": attrs,
    }


def get_json(hub, session, url):
    r = request(hub, session, url, timeout=TIMEOUT)
    if r is None:
        return None
    try:
        return r.json()
    except ValueError:
        hub.error()
        return None


def windows(hub, session, collection, start, end):
    """[(start, end, count)] covering [start, end), each small enough to page through; None if the catalogue failed."""
    d = get_json(hub, session, query_url(collection, start, end, 0))
    if d is None or "@odata.count" not in d:
        return None
    n = d["@odata.count"]
    if n <= MAX_SKIP + PAGE or end - start < (end - start).resolution * 1000:
        return [(start, end, n)]
    mid = start + (end - start) / 2
    a = windows(hub, session, collection, start, mid)
    if a is None:
        return None
    b = windows(hub, session, collection, mid, end)
    return None if b is None else a + b


def products(hub, session, collection, start, end):
    """All products of `collection` over India sensed in [start, end), or a str saying why not."""
    parts = windows(hub, session, collection, start, end)
    if parts is None:
        return "catalogue did not answer the count"
    out = []
    for a, b, n in parts:
        for skip in range(0, n, PAGE):
            d = get_json(hub, session, query_url(collection, a, b, PAGE, skip))
            if d is None or "value" not in d:
                return f"catalogue page {skip} of {_iso(a)[:10]}.. did not load"
            out += d["value"]
            time.sleep(max(0.5, hub.settings.get("delay_ms", 0) / 1000))
    seen = {p["Id"] for p in out}
    if len(seen) < sum(n for _, _, n in parts):
        return f"got {len(seen)} products of {sum(n for _, _, n in parts)}: the catalogue changed while paging"
    return out


def month_window(month):
    y, m = map(int, month.split("-"))
    start = datetime(y, m, 1, tzinfo=timezone.utc)
    return start, datetime(y + m // 12, m % 12 + 1, 1, tzinfo=timezone.utc)


def local(collection, month):
    hub = LocalHub()
    got = products(hub, requests.Session(), collection, *month_window(month))
    if isinstance(got, str):
        sys.exit(got)
    for p in got[:3]:
        rid, data = record(p)
        print(json.dumps({"record_id": rid, "data": data})[:600])
    print(f"{len(got)} products, counters {hub.counts}", file=sys.stderr)


def main():
    from scrape_hub_client import HubClient      # imported here so --local works without it
    hub = HubClient(PROJECT, job_index=int(os.environ.get("SCRAPE_JOB_INDEX", "0")), total_jobs=int(os.environ.get("SCRAPE_TOTAL_JOBS", "1")))
    session = requests.Session()
    try:
        while time.time() < DEADLINE:
            if hub.settings.get("paused"):
                time.sleep(30)                          # the hub holds us (site down, or the family owner paused it)
                continue
            items = hub.claim(1, steal=True, retry_failed=True)
            if not items:
                break                                   # nothing left for this project: exit, the worker asks the hub for more
            item, payload = items[0], items[0]["payload"]
            got = products(hub, session, payload["collection"], *month_window(payload["month"]))
            if isinstance(got, str):
                hub.failure("catalogue", item["key"], got)
                hub.complete([item["key"]], "failed", error=got[:200])
                continue
            rows = [record(p) for p in got]
            if rows:
                lines = "".join(json.dumps({"id": rid, **data}, separators=(",", ":")) + "\n" for rid, data in rows)
                hub.upload_many([(f"{payload['collection']}/{payload['month']}.jsonl.gz", gzip.compress(lines.encode()),
                                  "application/gzip")])
            for rid, data in rows:
                hub.record(rid, data)
            hub.clear_failure("catalogue", item["key"])
            hub.complete([item["key"]], "done", fetched=len(rows))
        hub.close()
    except BaseException as e:
        hub.close("failed", f"{type(e).__name__}: {e}"[:200])
        raise


if __name__ == "__main__":
    if sys.argv[1:2] == ["--local"]:
        local(sys.argv[2] if len(sys.argv) > 2 else "SENTINEL-5P", sys.argv[3] if len(sys.argv) > 3 else "2025-09")
    else:
        main()
