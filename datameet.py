"""The family's `datameet` task (see scrape.json): DataMeet's open datasets (github.com/datameet) into the family's bucket.
Try it without the hub: python datameet.py --local [repo]   (downloads that repo's current snapshot, prints the inventory)

Each queue item is one repo at one commit (family.py's datameet_items). We download GitHub's tarball of that commit from
codeload.github.com (no git history, no API calls: those are rate-limited), check that the archive names the commit we asked for,
store it at <project>/<repo>/<sha>.tar.gz, and keep one record for the repo (id = the repo name) and one per file in it
(id = "<repo>/<path>"), so the team can find a dataset without unpacking anything.
"""
import json
import os
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import PurePosixPath

import requests

from common import LocalHub, download, request

PROJECT = os.environ.get("SCRAPE_POOL_PROJECT", "")
BUDGET_S = float(os.environ.get("SCRAPE_MAX_HOURS", "1")) * 3600
DEADLINE = time.time() + BUDGET_S - 120
NEEDS_S = min(15 * 60, BUDGET_S / 4)    # don't start a repo with less time left: the biggest is over a GB
TIMEOUT = (30, 300)                      # codeload builds big tarballs before the first byte


def inventory(tar):
    """(commit sha from the archive's header, commit time, [(path, bytes)]) of a GitHub tarball (open tarfile). Pure."""
    files, mtime = [], 0
    for m in tar:
        if m.isfile():
            parts = PurePosixPath(m.name).parts[1:]       # drop the "<repo>-<sha>/" top folder
            files.append(("/".join(parts), m.size))
            mtime = max(mtime, m.mtime)
    when = datetime.fromtimestamp(mtime, timezone.utc).isoformat() if mtime else None
    return tar.pax_headers.get("comment", ""), when, files


def records(repo, sha, when, files):
    """[(record id, data)]: the repo, then each of its files. Pure."""
    base = f"https://github.com/datameet/{repo}"
    rows = [(repo, {"kind": "repo", "repo": repo, "sha": sha, "commit_time": when, "files": len(files),
                    "bytes": sum(n for _, n in files), "github_url": base,
                    "license_files": [p for p, _ in files if "/" not in p and p.upper().startswith(("LICENSE", "LICENCE", "COPYING"))],
                    "readme": next((p for p, _ in files if "/" not in p and p.upper().startswith("README")), None)})]
    for path, n in files:
        suffix = PurePosixPath(path).suffix.lower().lstrip(".")
        rows.append((f"{repo}/{path}", {"kind": "file", "repo": repo, "path": path, "bytes": n, "ext": suffix, "sha": sha,
                                         "github_url": f"{base}/blob/{sha}/{path}"}))
    return rows


def fetch_repo(hub, session, payload, tmp):
    """Download the item's tarball into file `tmp`: (tar bytes, md5, records) or a str saying why it failed."""
    r = request(hub, session, payload["url"], stream=True, timeout=TIMEOUT)
    if r is None:
        return "tarball did not answer"
    try:
        n, md5 = download(hub, r, tmp)
    except requests.RequestException as e:
        hub.metric("http_error")
        hub.error()
        return f"download broke off: {type(e).__name__}"
    tmp.seek(0)
    try:
        with tarfile.open(fileobj=tmp, mode="r:gz") as tar:
            sha, when, files = inventory(tar)
    except (tarfile.TarError, EOFError, OSError) as e:
        return f"not a readable tarball: {type(e).__name__}"
    if sha != payload["sha"]:
        return f"archive is commit {sha[:12] or '?'}, not {payload['sha'][:12]}"
    return n, md5, records(payload["repo"], sha, when, files)


def local(repo):
    import subprocess
    sha = subprocess.run(["git", "ls-remote", f"https://github.com/datameet/{repo}", "HEAD"], capture_output=True, text=True,
                         check=True).stdout.split()[0]
    hub = LocalHub()
    with tempfile.TemporaryFile() as tmp:
        got = fetch_repo(hub, requests.Session(), {"repo": repo, "sha": sha,
                                                   "url": f"https://codeload.github.com/datameet/{repo}/tar.gz/{sha}"}, tmp)
    if isinstance(got, str):
        sys.exit(got)
    n, md5, rows = got
    for rid, data in rows[:6]:
        print(json.dumps({"record_id": rid, "data": data}, ensure_ascii=False))
    print(f"{len(rows) - 1} files, tarball {n} bytes, counters {hub.counts}", file=sys.stderr)


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
            item, payload = items[0], items[0]["payload"]
            with tempfile.TemporaryFile() as tmp:
                got = fetch_repo(hub, session, payload, tmp)
                if isinstance(got, str):
                    hub.failure("tarball", item["key"], got, url=payload["url"])
                    hub.complete([item["key"]], "failed", error=got[:200])
                    continue
                n, md5, rows = got
                tmp.seek(0)
                stored = hub.upload_many([(f"{payload['repo']}/{payload['sha']}.tar.gz", tmp.read(), "application/gzip")])[0]
            rid, repo_data = rows[0]
            hub.record(rid, {**repo_data, "tar_bytes": n, "md5": md5, "sha256": stored["sha256"], "key": stored["key"],
                             "tarball_url": payload["url"]})
            for rid, data in rows[1:]:
                hub.record(rid, data)
            hub.clear_failure("tarball", item["key"])
            hub.complete([item["key"]], "done", fetched=len(rows))
            time.sleep(max(0.5, hub.settings.get("delay_ms", 0) / 1000))
        hub.close()
    except BaseException as e:
        hub.close("failed", f"{type(e).__name__}: {e}"[:200])
        raise


if __name__ == "__main__":
    if sys.argv[1:2] == ["--local"]:
        local(sys.argv[2] if len(sys.argv) > 2 else "Pune_wards")
    else:
        main()
