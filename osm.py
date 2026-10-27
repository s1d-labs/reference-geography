"""The family's `osm` task (see scrape.json): OpenStreetMap India extracts from Geofabrik into the family's bucket.
Try it without the hub: python osm.py --local [url]   (resolves the file and its checksum, no download)

Each queue item is one Geofabrik `*-latest*` URL. Geofabrik answers it with a redirect to the dated file of that day
(india-latest.osm.pbf -> india-261025.osm.pbf), which never changes afterwards; we download that dated file, check it against
Geofabrik's .md5 (published for .osm.pbf, not for .gpkg.zip) and its Content-Length, store it at
<project>/<YYYY-MM-DD>/<dated name> through the hub's signed upload link, and keep one record per file, id = the dated name.
"""
import json
import os
import re
import sys
import tempfile
import time

import requests

from common import LocalHub, download, request

PROJECT = os.environ.get("SCRAPE_POOL_PROJECT", "")
BUDGET_S = float(os.environ.get("SCRAPE_MAX_HOURS", "1")) * 3600
DEADLINE = time.time() + BUDGET_S - 120
NEEDS_S = min(15 * 60, BUDGET_S / 4)    # don't start a file with less time left: the biggest takes minutes to fetch and to store
DATED = re.compile(r"^(?P<region>[a-z-]+?)-(?P<yymmdd>\d{6})(?P<free>-free)?\.(?P<format>osm\.pbf|gpkg\.zip|shp\.zip)$")
CONTENT_TYPES = {"osm.pbf": "application/octet-stream", "gpkg.zip": "application/zip", "shp.zip": "application/zip"}


def snapshot(name):
    """What a dated Geofabrik file name says: {region, date, format}, or None if it isn't one. Pure."""
    m = DATED.match(name)
    if not m:
        return None
    d = m["yymmdd"]
    return {"region": m["region"], "date": f"20{d[:2]}-{d[2:4]}-{d[4:]}", "format": m["format"]}


def parse_md5(text, name):
    """The md5 in a Geofabrik .md5 file ("<hex>  <name>") if it is for `name`, else None. Pure."""
    parts = text.split()
    if len(parts) == 2 and re.fullmatch(r"[0-9a-f]{32}", parts[0]) and parts[1] == name:
        return parts[0]
    return None


def resolve(hub, session, url):
    """(open streaming response, dated name, info, md5 or None) for a `latest` URL, or a str saying why not."""
    r = request(hub, session, url, stream=True)
    if r is None:
        return "file did not answer"
    name = r.url.rsplit("/", 1)[-1]
    info = snapshot(name)
    if info is None:
        r.close()
        return f"not a dated file: {name}"
    md5 = None
    if info["format"] == "osm.pbf":
        m = request(hub, session, r.url + ".md5")
        md5 = m and parse_md5(m.text, name)
        if not md5:
            r.close()
            return f"no checksum for {name}"
    return r, name, info, md5


def fetch_file(hub, session, url):
    """Download one item's file and check it: (name, info, data bytes, record) or a str saying why it failed."""
    got = resolve(hub, session, url)
    if isinstance(got, str):
        return got
    r, name, info, md5 = got
    length = int(r.headers.get("Content-Length") or 0)
    last_modified = r.headers.get("Last-Modified", "")
    final_url = r.url
    with tempfile.TemporaryFile() as tmp:
        try:
            n, got_md5 = download(hub, r, tmp)
        except requests.RequestException as e:
            hub.metric("http_error")
            hub.error()
            return f"download broke off: {type(e).__name__}"
        if length and n != length:
            return f"{name}: got {n} of {length} bytes"
        if md5 and got_md5 != md5:
            return f"{name}: md5 {got_md5} is not Geofabrik's {md5}"
        tmp.seek(0)
        data = tmp.read()
    record = {**info, "file": name, "url": final_url, "latest_url": url, "bytes": n, "md5": got_md5,
              "md5_checked": bool(md5), "last_modified": last_modified, "source": "Geofabrik GmbH, © OpenStreetMap contributors (ODbL)"}
    return name, info, data, record


def local(url):
    hub = LocalHub()
    got = resolve(hub, requests.Session(), url)
    if isinstance(got, str):
        print(got, file=sys.stderr)
    else:
        r, name, info, md5 = got
        r.close()
        print(json.dumps({"record_id": name, "data": {**info, "url": r.url, "bytes": int(r.headers.get("Content-Length") or 0),
                                                       "md5": md5, "path": f"{info['date']}/{name}"}}))
    print(f"counters {hub.counts}", file=sys.stderr)


def main():
    from scrape_hub_client import HubClient      # imported here so --local works without it
    hub = HubClient(PROJECT, job_index=int(os.environ.get("SCRAPE_JOB_INDEX", "0")), total_jobs=int(os.environ.get("SCRAPE_TOTAL_JOBS", "1")))
    session = requests.Session()
    try:
        while time.time() < DEADLINE - NEEDS_S:
            if hub.settings.get("paused"):
                time.sleep(30)                          # the hub holds us (site down, or the family owner paused it)
                continue
            items = hub.claim(1, steal=True, retry_failed=True)
            if not items:
                break                                   # nothing left for this project: exit, the worker asks the hub for more
            item = items[0]
            got = fetch_file(hub, session, item["payload"]["url"])
            if isinstance(got, str):
                hub.failure("download", item["key"], got, url=item["payload"]["url"])
                hub.complete([item["key"]], "failed", error=got[:200])
                continue
            name, info, data, record = got
            stored = hub.upload_many([(f"{info['date']}/{name}", data, CONTENT_TYPES[info["format"]])])[0]
            del data
            hub.record(name, {**record, "key": stored["key"], "sha256": stored["sha256"], "item": item["key"]})
            hub.clear_failure("download", item["key"])
            hub.complete([item["key"]], "done", fetched=1)
            time.sleep(max(0.5, hub.settings.get("delay_ms", 0) / 1000))
        hub.close()
    except BaseException as e:
        hub.close("failed", f"{type(e).__name__}: {e}"[:200])
        raise


if __name__ == "__main__":
    if sys.argv[1:2] == ["--local"]:
        local(sys.argv[2] if len(sys.argv) > 2 else "https://download.geofabrik.de/asia/india-latest.osm.pbf")
    else:
        main()
