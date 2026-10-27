"""The family's `bhuvan` task (see scrape.json): the catalogue of map layers ISRO's Bhuvan geoportal publishes over WMS.
Try it without the hub: python bhuvan.py --local [capabilities-url]   (prints the first records and the layer count)

Each queue item is one Bhuvan GeoServer's full WMS GetCapabilities (bhuvan-vec1 about 6,700 layers and 10 MB, bhuvan-vec2 about
3,800). We keep the raw document, gzipped, at <project>/<YYYY-MM-DD>/wms-capabilities.xml.gz and one record per layer,
id = the layer name (e.g. "nuis:AP_TP_UL10K"). Only the catalogue: Bhuvan's WFS is off and its data policy keeps the vector
databases for authorised (government) users, so the layers' features are not fetched.
"""
import gzip
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

from common import LocalHub, request

PROJECT = os.environ.get("SCRAPE_POOL_PROJECT", "")
DEADLINE = time.time() + float(os.environ.get("SCRAPE_MAX_HOURS", "1")) * 3600 - 120
WMS = "{http://www.opengis.net/wms}"
XLINK = "{http://www.w3.org/1999/xlink}"
TIMEOUT = (30, 300)          # bhuvan-vec2 takes up to two minutes to start answering a full GetCapabilities


def _text(el, tag):
    t = el.find(WMS + tag)
    return (t.text or "").strip() if t is not None else ""


def _float(el, tag):
    try:
        return float(_text(el, tag))
    except ValueError:
        return None


def parse(xml):
    """[(layer name, data)] for every named layer in a WMS 1.3.0 capabilities document (bytes). Pure."""
    root = ET.fromstring(xml)
    out = []
    for layer in root.iter(WMS + "Layer"):
        name = _text(layer, "Name")
        if not name:
            continue                        # the root layer only groups the others
        box = layer.find(WMS + "EX_GeographicBoundingBox")
        bbox = None
        if box is not None:
            bbox = [_float(box, "westBoundLongitude"), _float(box, "southBoundLatitude"),
                    _float(box, "eastBoundLongitude"), _float(box, "northBoundLatitude")]
            if None in bbox or bbox[0] > bbox[2] or bbox[1] > bbox[3]:
                bbox = None                 # GeoServer writes 0,0,-1,-1 for layers without a known extent
        styles = []
        for st in layer.findall(WMS + "Style"):
            legend = st.find(f"{WMS}LegendURL/{WMS}OnlineResource")
            styles.append({"name": _text(st, "Name"), "title": _text(st, "Title"),
                           "legend_url": legend.get(XLINK + "href") if legend is not None else None})
        out.append((name, {
            "name": name,
            "workspace": name.split(":", 1)[0] if ":" in name else "",
            "title": _text(layer, "Title"),
            "abstract": _text(layer, "Abstract"),
            "keywords": [k.text.strip() for k in layer.iterfind(f"{WMS}KeywordList/{WMS}Keyword") if k.text and k.text.strip()],
            "crs": [c.text.strip() for c in layer.findall(WMS + "CRS") if c.text],
            "bbox": bbox,
            "queryable": layer.get("queryable") == "1",
            "min_scale": _float(layer, "MinScaleDenominator"),
            "max_scale": _float(layer, "MaxScaleDenominator"),
            "styles": styles,
        }))
    return out


def local(url):
    r = request(LocalHub(), requests.Session(), url, timeout=TIMEOUT)
    if r is None:
        sys.exit("capabilities did not load")
    rows = parse(r.content)
    for rid, data in rows[:5]:
        print(json.dumps({"record_id": rid, "data": data}, ensure_ascii=False))
    print(f"{len(rows)} layers", file=sys.stderr)


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
            item = items[0]
            url = item["payload"]["url"]
            r = request(hub, session, url, timeout=TIMEOUT)
            try:
                rows = parse(r.content) if r is not None else None
            except ET.ParseError:
                rows = None
            if not rows:
                why = "capabilities did not load" if r is None else "capabilities did not parse or list no layers"
                hub.failure("capabilities", item["key"], why, url=url)
                hub.complete([item["key"]], "failed", error=why)
                continue
            day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            stored = hub.upload_many([(f"{day}/wms-capabilities.xml.gz", gzip.compress(r.content), "application/gzip")])[0]
            server = url.split("/")[2]
            for rid, data in rows:
                hub.record(rid, {**data, "server": server, "wms_url": url.split("?")[0], "seen": day, "capabilities": stored["key"]})
            hub.clear_failure("capabilities", item["key"])
            hub.complete([item["key"]], "done", fetched=len(rows))
            time.sleep(max(0.5, hub.settings.get("delay_ms", 0) / 1000))
        hub.close()
    except BaseException as e:
        hub.close("failed", f"{type(e).__name__}: {e}"[:200])
        raise


if __name__ == "__main__":
    if sys.argv[1:2] == ["--local"]:
        local(sys.argv[2] if len(sys.argv) > 2 else "https://bhuvan-vec2.nrsc.gov.in/bhuvan/wms?service=WMS&version=1.3.0&request=GetCapabilities")
    else:
        main()
