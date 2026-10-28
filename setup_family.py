"""Put this family's projects in the pool and register its health checks. Run by the Setup workflow (GitHub Actions: the hub
trusts this repo, s1d-labs/<family>, through its OIDC token). Safe to run again: queue items that exist are kept."""
from scrape_hub_client import register_project, seed_queue, set_pool, set_probes

from family import FAMILY, PROBES, PROJECTS

print("health checks:", set_probes(FAMILY, PROBES))
failed = []
for p in PROJECTS:
    try:
        items = p["items"]() if callable(p["items"]) else p["items"]   # a function when the queue depends on the site's state now
    except Exception as e:  # noqa: BLE001
        # the site could not be listed right now: still apply the project's pool settings (worker cap, task, probe), and leave
        # its queue as it is until the next run
        items = None
        failed.append(f"{p['name']}: {type(e).__name__}: {e}"[:300])
    if items is not None:
        register_project(p["name"], title=p["title"], unit_label=p["unit_label"], record_label=p["record_label"],
                         expected_units=len(items), expected_records=sum(i["payload"].get("expected", 0) for i in items))
    set_pool(p["name"], FAMILY, p["task"], target=p["target"], env=p["env"], probe=p["probe"], max_workers=p.get("max_workers"))
    print(p["name"], "queue:", seed_queue(p["name"], items) if items is not None else "not listed (kept as it is)")
if failed:
    raise SystemExit("could not list: " + "; ".join(failed))           # the run shows red, but every pool setting was applied
