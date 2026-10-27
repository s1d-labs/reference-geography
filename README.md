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

### `reference-geography-bhuvan-vec1`, `-vec2`: Bhuvan WMS layer catalogue (ISRO / NRSC)

The list of map layers [Bhuvan](https://bhuvan.nrsc.gov.in) publishes on its two vector GeoServers, `bhuvan-vec1.nrsc.gov.in`
(about 6,700 layers) and `bhuvan-vec2.nrsc.gov.in` (about 4,600; Oct 2026). Workspaces include `nuis` (urban
land use 10K), `sisdp`/`sisdpv2` (10K maps), `lulc`, `wasteland`, `disaster`, `pmgsy`, `vill-census`, `admin`, `postal`.

- **Queue**: one item per server per month, key `YYYY-MM/capabilities`, seeded by the same monthly **setup** run.
- **Task** `bhuvan` (`bhuvan.py`): fetches the server's full WMS 1.3.0 GetCapabilities (vec2 can take two minutes to answer), stores
  it gzipped at `<project>/<YYYY-MM-DD>/wms-capabilities.xml.gz`, and keeps one record per layer, id = layer name (`nuis:AP_TP_UL10K`):
  `workspace`, `title`, `abstract`, `keywords`, `crs`, `bbox` [w, s, e, n] (null when the server doesn't know it), `queryable`,
  `min_scale`, `max_scale`, `styles` (with legend URLs), `server`, `wms_url`, `seen` (the day of the last catalogue that listed it).
- **Health check**: a 1 KB legend image (`moef:biosphere`) per server; the capabilities are 220 KB even for an empty workspace.
- **Only the catalogue.** Bhuvan's WFS is off, and its data policy grants a single-user licence and keeps the vector databases for
  authorised (government) users, so features are not fetched. Cite as "Bhuvan, NRSC/ISRO".

### `reference-geography-datameet`: DataMeet open datasets (github.com/datameet)

Snapshots of 33 of [DataMeet](https://github.com/datameet)'s repositories, about 6.4 GB unpacked: maps (`maps`,
`indian_village_boundaries`, `India_Official_Boundaries_2019`, `shapefiles`, `taluk_boundaries`, `indian-district-boundaries`,
`Municipal_Spatial_Data`, `PincodeBoundary`, `kgis`, `landuse_maps`, `pmgsy-geosadak`), pincodes and post offices, the Local
Government Directory, railways, schools (`udise_schools`), elections, COVID-19 and more (`DATAMEET` in `family.py`).

- **Queue**: one item per repo per commit, key `<repo>@<sha12>`. The monthly **setup** run asks GitHub for each repo's current
  commit (`git ls-remote`), so a repo is fetched again only when DataMeet changes it.
- **Task** `datameet` (`datameet.py`): downloads codeload.github.com's tarball of that commit (no history, no rate-limited API),
  checks the commit id inside the archive, stores it at `<project>/<repo>/<sha>.tar.gz`, and keeps one record per repo
  (id = repo: `sha`, `commit_time`, `files`, `bytes`, `tar_bytes`, `md5`, `sha256`, `key`, `license_files`, `readme`) and one per
  file (id = `<repo>/<path>`: `path`, `bytes`, `ext`, `github_url`), so datasets can be found with SQL before unpacking anything.
- **Left out**: software forks and websites, the mailing-list and chat archives (people's messages), `covid19_stories_archive`
  (copies of news articles, 3 GB+), `geoBoundaries` (a fork kept in Git LFS; the original is at geoboundaries.org).
- **Licences differ per repo** (many are ODbL or CC BY; several state none): check `license_files` / the README before
  publishing anything built on them, and credit DataMeet and the original sources.

## Working here

```
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pytest "scrape-hub-client @ git+https://github.com/s1d-labs/runner@main#subdirectory=sdk"
python -m pytest tests -q
python osm.py --local [latest-url]     # resolve one file and its checksum, no download
python bhuvan.py --local [caps-url]    # parse one Bhuvan catalogue, print the first layers
python datameet.py --local [repo]      # download one DataMeet repo snapshot, print its inventory
scrape-check --items 2                 # setup + osm task against a local stand-in hub (downloads the two smallest files)
scrape-check --project reference-geography-bhuvan-vec2 --items 1
scrape-check --project reference-geography-datameet --items 4
```
