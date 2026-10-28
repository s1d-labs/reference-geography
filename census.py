"""The family's `census` task (see scrape.json): Census of India's catalogue (censusindia.gov.in, NADA) into the family's bucket.
Try it without the hub: python census.py --local table PC11_A02     or     python census.py --local doc <catalogue id>

Two kinds of queue item, listed from the catalogue by setup (family.py):
- table/<table id>: one census table (1991, 2001, 2011; 779 of them) with every file it offers, India, state and district
  (Excel, some PDF): stored at <project>/tables/<year>/<table id>/<download id>-<file>.
- doc/<catalogue id>: one entry of the digital library (reports back to the 1870s, handbooks, notes, circulars; also the
  historical photos and videos): its catalogue page lists the files, stored at <project>/library/<year>/<id>/<download id>-<file>
  (the download id keeps names apart that only differ in non-Latin letters, which the bucket's paths can't hold).
One record per file, id = file/<catalogue id>/<download id> (NADA's own ids), and one per table or library entry.
The site's firewall answers some URLs with a "Request Rejected" page (the detailed API, for one); we stay on the public
listing API and catalogue pages, count a rejection as a refusal (hub.block()) and fail the item for a later retry.
"""
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote

import requests

from common import LocalHub, download, request

PROJECT = os.environ.get("SCRAPE_POOL_PROJECT", "")
BUDGET_S = float(os.environ.get("SCRAPE_MAX_HOURS", "1")) * 3600
DEADLINE = time.time() + BUDGET_S - 120
NEEDS_S = min(15 * 60, BUDGET_S / 4)
NADA = "https://censusindia.gov.in/nada/index.php"
UA = "s1d-labs scraper (https://github.com/s1d-labs)"
LIBRARY_TYPES = ("document", "image", "video", "timeseries")
DOWNLOAD = re.compile(r"https://censusindia\.gov\.in/nada/index\.php/catalog/(\d+)/download/(\d+)/([^\"'<>\s]+)")
REJECTED = "Request Rejected"


def list_tables(session=None):
    """Every census table with its files: [{"table_id", "title", "census_year", "series", "files": [...]}]."""
    s = session or requests.Session()
    out, offset = [], 0
    while True:
        d = s.get(f"{NADA}/api/tables/data/global/census_tables/300/{offset}/?ft_query=", timeout=300,
                  headers={"User-Agent": UA}).json()
        for t in d["data"]:
            files = [{"url": l["link"], "format": l["format"].lower(), "area": "", "state": "", "district": ""} for l in t.get("links") or []]
            for it in t.get("items") or []:
                files += [{"url": l["link"], "format": l["format"].lower(), "area": it.get("table_id", ""),
                           "state": it.get("state_name", ""), "district": it.get("district_name", "")} for l in it.get("links") or []]
            out.append({"table_id": t["table_id"], "title": t["title"], "census_year": t.get("census_year"),
                        "series": [x["series_title"] for x in t.get("series") or []], "files": files})
        offset += len(d["data"])
        if not d["data"] or offset >= d["found"]:
            return out


def list_library(session=None):
    """Every library entry (documents, photos, videos): [{"id", "idno", "title", "type", "year"}]."""
    s = session or requests.Session()
    out = []
    seen = set()
    for kind in LIBRARY_TYPES:
        page = 1                                    # the search pages by `page`; it ignores `offset`
        while True:
            r = s.get(f"{NADA}/api/catalog/search", params={"ps": 100, "type": kind, "page": page}, timeout=120,
                      headers={"User-Agent": UA}).json()["result"]
            for x in r["rows"]:
                if int(x["id"]) not in seen:
                    seen.add(int(x["id"]))
                    out.append({"id": int(x["id"]), "idno": x["idno"], "title": x.get("title") or "",
                                "type": x.get("type") or kind, "year": x.get("year_start")})
            if not r["rows"] or page * 100 >= int(r["found"]):
                break
            page += 1
            time.sleep(0.5)
    return out


def download_links(page):
    """[(catalogue id, download id, file name)] on a catalogue page, in page order, each once. Pure."""
    seen, out = set(), []
    for cid, rid, name in DOWNLOAD.findall(page):
        if rid not in seen:
            seen.add(rid)
            out.append((cid, rid, unquote(name)))
    return out


def safe(name):
    """A file name the bucket accepts ([A-Za-z0-9._-]). Pure."""
    return re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9._-]", "_", name)).strip("_") or "file"


def store(hub, session, url, path, rid, meta):
    """Download one file and store it at `path`; the record, or a str saying why not."""
    r = request(hub, session, url, stream=True, timeout=(30, 300))
    if r is None:
        return "did not download"
    if r.headers.get("Content-Type", "").startswith("text/html"):
        page = r.text
        if REJECTED in page:
            hub.block()
            return "rejected by the site's firewall"
        return "got a web page, not a file"
    with tempfile.TemporaryFile() as tmp:
        try:
            n, md5 = download(hub, r, tmp)
        except requests.RequestException:
            hub.metric("http_error")
            hub.error()
            return "download broke off"
        tmp.seek(0)
        stored = hub.upload_many([(path, tmp.read(), "application/octet-stream")])[0]
    return {**meta, "url": url, "bytes": n, "md5": md5, "sha256": stored["sha256"], "key": stored["key"]}


def run_table(hub, session, p):
    n, failed = 0, []
    for f in p["files"]:
        m = DOWNLOAD.match(f["url"])
        if not m:
            continue
        cid, rid, name = m.group(1), m.group(2), unquote(m.group(3))
        got = store(hub, session, f["url"], f"tables/{p['census_year']}/{safe(p['table_id'])}/{rid}-{safe(name)}", rid,
                    {"kind": "table_file", "table_id": p["table_id"], "census_year": p["census_year"], "file": name,
                     "format": f["format"], "area_id": f["area"], "state": f["state"], "district": f["district"]})
        if isinstance(got, str):
            failed.append(f"{name}: {got}")
            hub.failure("file", f"file/{cid}/{rid}", got, url=f["url"])
            if "firewall" in got:
                break                                   # stop knocking; the hub retries the item later
            continue
        hub.record(f"file/{cid}/{rid}", got)
        n += 1
        time.sleep(max(0.5, hub.settings.get("delay_ms", 0) / 1000))
    hub.record(f"table/{p['table_id']}", {"kind": "table", "table_id": p["table_id"], "title": p["title"],
                                          "census_year": p["census_year"], "series": p["series"], "files": len(p["files"])})
    return n + 1, (f"{len(failed)} of {len(p['files'])} files failed: {failed[0]}" if failed else None)


def run_doc(hub, session, p):
    url = f"{NADA}/catalog/{p['id']}"
    r = request(hub, session, url, timeout=(30, 120))
    if r is None:
        return 0, "catalogue page did not load"
    if REJECTED in r.text:
        hub.block()
        return 0, "catalogue page rejected by the site's firewall"
    links = download_links(r.text)
    n, failed = 0, []
    year = str(p.get("year") or "undated")
    for cid, rid, name in links:
        got = store(hub, session, f"{NADA}/catalog/{cid}/download/{rid}/{name}",
                    f"library/{safe(year)}/{p['id']}/{rid}-{safe(name)}", rid,
                    {"kind": "library_file", "entry_id": p["id"], "idno": p["idno"], "file": name})
        if isinstance(got, str):
            failed.append(f"{name}: {got}")
            hub.failure("file", f"file/{cid}/{rid}", got)
            if "firewall" in got:
                break
            continue
        hub.record(f"file/{cid}/{rid}", got)
        n += 1
        time.sleep(max(0.5, hub.settings.get("delay_ms", 0) / 1000))
    hub.record(f"entry/{p['idno']}", {"kind": "library_entry", "entry_id": p["id"], "idno": p["idno"], "title": p["title"],
                                      "type": p["type"], "year": p.get("year"), "url": url, "files": len(links)})
    return n + 1, (f"{len(failed)} of {len(links)} files failed: {failed[0]}" if failed else None)


def run(hub, session, item):
    return (run_table if item["payload"]["kind"] == "table" else run_doc)(hub, session, item["payload"])


def local(kind, ident):
    s = requests.Session()
    if kind == "table":
        p = {"kind": "table", **next(t for t in list_tables(s) if t["table_id"] == ident)}
        p["files"] = p["files"][:3]                     # a taste, not the whole table
    else:
        p = {"kind": "doc", "id": int(ident), "idno": ident, "title": "", "type": "document", "year": None}

    class Hub(LocalHub):
        def record(self, rid, data):
            print(json.dumps({"record_id": rid, "data": data}, ensure_ascii=False)[:400])

        def failure(self, kind, key, reason, **detail):
            print(f"failure {key}: {reason}", file=sys.stderr)

        def upload_many(self, files):
            return [{"key": path, "sha256": "-"} for path, _, _ in files]

    hub = Hub()
    n, why = run(hub, s, {"payload": p})
    print(f"{n} records, {why or 'all files stored'}, counters {hub.counts}", file=sys.stderr)


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
            n, why = run(hub, session, item)
            hub.complete([item["key"]], "failed" if why else "done", error=(why or "")[:200] or None, fetched=n)
        hub.close()
    except BaseException as e:
        hub.close("failed", f"{type(e).__name__}: {e}"[:200])
        raise


if __name__ == "__main__":
    if sys.argv[1:2] == ["--local"]:
        local(sys.argv[2] if len(sys.argv) > 2 else "table", sys.argv[3] if len(sys.argv) > 3 else "PC11_A02")
    else:
        main()
