# reference-geography

Geography, reference and location datasets for the s1d-labs scrape pool. The pool runs this code on members' GitHub Actions
minutes, coordinated by [scrape.s1d.me](https://scrape.s1d.me); the full contract is in `CLAUDE.md`.

## Projects

### `reference-geography-osm-india`: OpenStreetMap India (Geofabrik)

Monthly snapshots of the [Geofabrik India extract](https://download.geofabrik.de/asia/india.html), 13 files, about 7.5 GB:

| File | Format | Size (Oct 2026) |
|---|---|---|
| `india-YYMMDD.osm.pbf` | whole country, OSM PBF | 1.7 GB |
| `<zone>-zone-YYMMDD.osm.pbf` × 6 | central, eastern, north-eastern, northern, southern, western | 1.7 GB together |
| `<zone>-zone-YYMMDD-free.gpkg.zip` × 6 | the same zones as GeoPackage (Geofabrik's "free" layers) | 4.1 GB together |

- **Queue**: one item per file per month, key `YYYY-MM/<file>` (`family.py`). The **setup** workflow runs on the 2nd of each month
  and seeds that month's 13 items; existing keys are kept, so running it again by hand does nothing new that month.
- **Task** `osm` (`osm.py`): follows Geofabrik's `*-latest*` redirect to the dated file, downloads it, checks the byte count and,
  for `.osm.pbf`, Geofabrik's `.md5`, then uploads it through the hub. Two workers at most on `download.geofabrik.de`.
- **Files**: in the family's bucket at `reference-geography-osm-india/<YYYY-MM-DD>/<dated file>` (`mybucket ls -r reference-geography-osm-india/`).
- **Records**: one per file, id = the dated file name; `region`, `date`, `format`, `url`, `bytes`, `md5`, `md5_checked`,
  `sha256`, `last_modified`, `key` (bucket key).

Data © OpenStreetMap contributors, available under the [ODbL](https://opendatacommons.org/licenses/odbl/); extracts by Geofabrik GmbH.

## Working here

```
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pytest "scrape-hub-client @ git+https://github.com/s1d-labs/runner@main#subdirectory=sdk"
python -m pytest tests -q
python osm.py --local [latest-url]     # resolve one file and its checksum, no download
scrape-check --items 2                 # setup + task against a local stand-in hub (downloads the two smallest files)
```
