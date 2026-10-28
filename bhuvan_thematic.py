"""The family's `bhuvan-thematic` task (see scrape.json): Bhuvan's public thematic statistics and documents (NRSC/ISRO).
Try it without the hub: python bhuvan_thematic.py --local <item key>   (e.g. stats/wl1516/AP, lulc250/2324/Annual, docs/fldhz)

What the Thematic Services page shows anyone (bhuvan-app1.nrsc.gov.in/thematic): area statistics for land use / land cover
(50K: 2005-06, 2011-12, 2015-16; 250K: 2005-06 to 2024-25 by season), land degradation, wasteland and flood hazard, by state
and, where Bhuvan has them, by district; and the technical documents, atlases and state maps it links. The structure (themes,
states, census codes, document paths, 250K years and seasons) was read from the page once and is kept in bhuvan_thematic.json.
Not the layers' features: Bhuvan keeps those for authorised users. The district lists Bhuvan sends carry each district's
boundary; we keep the code and name only.

Queue items (family.py): stats/<theme>/<state> (the state's page and its districts'), lulc250/<year>/<season> (India and each
state), docs/<theme> (that theme's documents). One record per statistics page, id = <theme>/<state>[/<district code>] or
lulc250/<year>/<season>/<region>; one per document, id = doc/<path>, the file itself at <project>/docs/<path>.
"""
import html
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

import requests

from common import LocalHub, download, request

PROJECT = os.environ.get("SCRAPE_POOL_PROJECT", "")
BUDGET_S = float(os.environ.get("SCRAPE_MAX_HOURS", "1")) * 3600
DEADLINE = time.time() + BUDGET_S - 120
NEEDS_S = min(10 * 60, BUDGET_S / 4)
SITE = "https://bhuvan-app1.nrsc.gov.in"
STATS = f"{SITE}/thematic/thematic/usertasks/download1"
DOCS = f"{SITE}/2dresources/thematic"
TIMEOUT = (20, 60)          # the server sometimes never answers; a retry usually does
TRIES = 3
DATA = json.loads((Path(__file__).parent / "bhuvan_thematic.json").read_text())
NO_MAP = {"gm", "ln", "glwb", "urbn", "lulc101619"}      # themes whose page links no state map (the page's own list)
CONTENT_TYPES = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def doc_paths(theme):
    """Document paths (under DOCS) the Thematic page links for `theme`, built with the page's own rules. Pure."""
    out = []
    if theme == "lulc250":
        for paths in DATA["lulc250"]["documents"].values():
            out += paths
    else:
        for code, census, name, doc, mp in DATA["themes"][theme]["states"]:
            out += [doc] if doc else []
            if theme in NO_MAP:
                continue
            if theme.startswith("lulc50"):
                out += [mp, mp.replace(".jpg", ".pdf")] if mp else []
            elif theme == "wl1516":
                out += ([mp] if mp else []) + ["wl1516/Wasteland_Atlas_2019_Full_opt.pdf"]
            elif theme == "lulc" and doc:
                out += [doc.replace(".pdf", "_2005-06.pdf").replace("LULC", "LULC/MAP", 1), doc.replace("LULC", "LULC/MAP/Stat", 1)]
            elif mp:
                out.append(mp)
    return sorted({p for p in out if p})


def _cells(row):
    return [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip() for c in re.findall(r"<td[^>]*>(.*?)(?=<td|</tr|$)", row, re.S | re.I)]


def _number(s):
    s = s.replace(",", "").strip()
    return float(s) if re.fullmatch(r"-?\d+(\.\d+)?", s) else None


def parse(page):
    """{title, period, place, total, total_label, unit, columns, rows} for one statistics page, or None when it has no table
    (Bhuvan's answer for a place it has no figures for). rows: [{"class": ..., "values": [numbers]}]. Pure."""
    page = re.sub(r"<title>.*?</title>", "", page, flags=re.S | re.I)      # "BHUVAN - ... Information": the browser tab
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " | ", page)))
    m = re.search(r"\|\s*([^|]*?(?:Information|statistics)[^|]*?)\s*\|", text)
    if not m:
        return None
    title = m.group(1).strip()
    period = re.search(r"\(([^)]*\d[^)]*)\)", title)
    place = re.search(r"\bfor (.+)$", title)
    total = re.search(r"(Total [^:|]*?)\s*:\s*\|?\s*([\d.,]+)\s*([^|]*?)\s*\|", text)
    rows, columns = [], []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S | re.I):
        cells = [c for c in _cells(tr) if c]
        group = None
        for c in cells:
            v = _number(c)
            if v is None:
                group = {"class": c, "values": []}
                rows.append(group)
            elif group is not None:
                group["values"].append(v)
        if cells and all(_number(c) is None for c in cells) and not columns:
            columns = cells
    rows = [r for r in rows if r["values"]]
    if not rows:
        return None
    unit = re.search(r"Area\s*\(([^)]+)\)", " ".join(columns))
    return {"title": title, "period": period.group(1) if period else None, "place": place.group(1).strip() if place else None,
            "total_label": total.group(1).strip() if total else None, "total": _number(total.group(2)) if total else None,
            "total_unit": total.group(3).strip() if total else None, "unit": unit.group(1) if unit else None,
            "columns": columns, "rows": rows}


def districts(page):
    """[(district code, name)] from Bhuvan's district list (each <option> also carries the boundary, which we drop). Pure."""
    return [(code, html.unescape(name).strip()) for code, name in re.findall(r"<option value='(\d+)_[^']*'[^>]*>([^<]*)", page)]


def fetch(hub, session, url):
    """The page's text, trying TRIES times (the server sometimes hangs); None if it never answered."""
    for i in range(TRIES):
        r = request(hub, session, url, timeout=TIMEOUT)
        if r is not None:
            return r.text
        time.sleep(2 * (i + 1))
    return None


def stats_pages(hub, session, payload):
    """[(record id, url, extra)] the item covers, or a str saying why it can't list them."""
    theme, state = payload["theme"], payload.get("state")
    if theme == "lulc250":
        y, season = payload["year"], payload["season"]
        # Kharif and Rabi pages are one national table by state, whatever state is asked for: India's is enough
        regions = DATA["lulc250"]["regions"] if season == "Annual" else DATA["lulc250"]["regions"][:1]
        return [(f"lulc250/{y}/{season}/{code}", f"{STATS}/theme_stats/lulc_lulc250.php?name={y}&state={quote(code)}&season={season}",
                 {"level": "country" if code == "IN" else "state", "region": code, "region_name": name, "year": y, "season": season})
                for code, name in regions]
    tail = "" if theme == "lulc" else "&state=IN"            # the page asks for 2005-06 without it
    out = [(f"{theme}/{state}", f"{STATS}/theme_stats/lulc_{theme}.php?name={state}{tail}",
            {"level": "state", "state": state, "census_code": payload.get("census"), "state_name": payload.get("name")})]
    if payload.get("districts") and payload.get("census"):
        page = fetch(hub, session, f"{STATS}/get/getDistricts.php?them={theme}&region=1&stateCode={payload['census']}")
        if page is None:
            return "district list did not load"
        for code, name in districts(page):
            out.append((f"{theme}/{state}/{code}", f"{STATS}/theme_stats/lulc_{theme}_dist.php?name={code}",
                        {"level": "district", "state": state, "district_code": code, "district_name": name}))
    return out


def run_stats(hub, session, item):
    """Store the item's statistics pages: (records stored, None) or (n, why it failed)."""
    payload = item["payload"]
    pages = stats_pages(hub, session, payload)
    if isinstance(pages, str):
        return 0, pages
    theme = payload["theme"]
    title = DATA["lulc250"]["title"] if theme == "lulc250" else DATA["themes"][theme]["title"]
    n, failed = 0, []
    for rid, url, extra in pages:
        page = fetch(hub, session, url)
        if page is None:
            failed.append(rid)
            hub.failure("page", rid, "did not answer", url=url)
            continue
        got = parse(page)
        if got is None:
            hub.metric("no_figures")                       # Bhuvan has no figures for this place: nothing to keep
            continue
        hub.record(rid, {"theme": theme, "theme_title": title, **extra, **got, "url": url})
        n += 1
        time.sleep(max(0.3, hub.settings.get("delay_ms", 0) / 1000))
    return n, (f"{len(failed)} of {len(pages)} pages did not answer" if failed else None)


def run_docs(hub, session, item):
    """Download and store the theme's documents: (records stored, None) or (n, why it failed)."""
    n, failed = 0, []
    for path in item["payload"]["paths"]:
        url = f"{DOCS}/{path}"
        safe = "/".join(re.sub(r"[^A-Za-z0-9._-]", "_", s) for s in path.split("/"))
        r = request(hub, session, url, stream=True, timeout=(20, 120), accept=(404,))
        if r is None:
            failed.append(path)                         # no answer or an error: the item is retried
            continue
        if r.status_code == 404:                        # a link the page offers to a file the server doesn't have
            r.close()
            hub.record(f"doc/{path}", {"kind": "document", "theme": item["payload"]["theme"], "path": path, "url": url,
                                        "missing": True})
            n += 1
            continue
        with tempfile.TemporaryFile() as tmp:
            try:
                size, md5 = download(hub, r, tmp)
            except requests.RequestException:
                hub.metric("http_error")
                failed.append(path)
                continue
            tmp.seek(0)
            stored = hub.upload_many([(f"docs/{safe}", tmp.read(),
                                       CONTENT_TYPES.get(Path(path).suffix.lower(), "application/octet-stream"))])[0]
        hub.record(f"doc/{path}", {"kind": "document", "theme": item["payload"]["theme"], "path": path, "url": url,
                                    "bytes": size, "md5": md5, "sha256": stored["sha256"], "key": stored["key"]})
        n += 1
    return n, (f"{len(failed)} of {len(item['payload']['paths'])} documents did not load: {', '.join(failed[:3])}" if failed else None)


def run(hub, session, item):
    return (run_docs if item["payload"]["kind"] == "docs" else run_stats)(hub, session, item)


def local(key):
    from family import PROJECTS
    item = next(i for p in PROJECTS if p["task"] == "bhuvan-thematic" for i in p["items"] if i["key"] == key)

    class Hub(LocalHub):
        def record(self, rid, data):
            print(json.dumps({"record_id": rid, "data": data}, ensure_ascii=False)[:400])

        def failure(self, kind, key, reason, **detail):
            print(f"failure {kind} {key}: {reason}", file=sys.stderr)

        def upload_many(self, files):
            return [{"key": p, "sha256": "-"} for p, _, _ in files]

    hub = Hub()
    n, why = run(hub, requests.Session(), item)
    print(f"{n} records, {why or 'all pages answered'}, counters {hub.counts}", file=sys.stderr)


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
            if why:
                hub.complete([item["key"]], "failed", error=why[:200], fetched=n)
            else:
                hub.complete([item["key"]], "done", fetched=n)
        hub.close()
    except BaseException as e:
        hub.close("failed", f"{type(e).__name__}: {e}"[:200])
        raise


if __name__ == "__main__":
    if sys.argv[1:2] == ["--local"]:
        local(sys.argv[2] if len(sys.argv) > 2 else "stats/fldhz/AS")
    else:
        main()
