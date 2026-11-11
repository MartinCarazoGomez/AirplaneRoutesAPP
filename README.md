# Flight Connections Clone (Starter)

This starter script creates an interactive world map with dots for commercial airports.
Clicking an airport draws lines to its outgoing destination airports.

Project convention: airport codes are IATA (3 letters).

## Data source

- Airport database: [OurAirports dataset](https://github.com/davidmegginson/ourairports-data)
- File used by the script: `airports.csv`
- Route database (primary): [Jonty/airline-route-data](https://github.com/Jonty/airline-route-data)
- Route database (fallback, legacy): [OpenFlights routes.dat](https://openflights.org/data)

## What counts as "commercial" in this first version

- Airport type is one of:
  - `large_airport`
  - `medium_airport`
  - `small_airport`
- `scheduled_service == yes`

## Run

```bash
python -m pip install -r requirements.txt
python app.py
```

This starts a local interactive server (default `http://127.0.0.1:8050`) where clicking an airport shows outgoing routes.
Interaction flow:
- First click: origin airport
- Second click: destination airport
- Left panel: airlines on that route + observed daily times (UTC) from `flights_export.csv` if available
- Left panel dropdown: filter by airline (shows only airports/routes connected by that airline)
The map now uses detailed cartographic tiles (Carto Positron) and stronger route edges for better readability.
Airport color bands are based on airport `type`:
- Dark Blue: `large_airport`
- Orange: `medium_airport`
- Red: `small_airport`
- Black: any other airport type

When downloading/saving `airports.csv`, rows with `type = heliport` are removed.
When run, it also downloads and saves:
- `airports.csv`
- `routes.csv`
- `airlines.csv`

## GitHub Pages

The published site is static HTML, CSS, and JavaScript in `docs/`. Python stays the data builder: it turns the local flight history into JSON the browser can load. The parquet files, `flights_export.csv`, and the schedule pickle stay on your machine and are listed in `.gitignore`.

Refresh the data after the route or schedule files change:

```bash
python export_site_data.py
```

Preview the site from the `docs` folder:

```bash
python -m http.server 8765
```

Then open `http://127.0.0.1:8765`. In the GitHub repository settings, set Pages to deploy from the `docs` folder on the default branch.

Both scripts include runtime instrumentation and timeout controls.  
If a network/file stage takes too long, they raise a clear timeout error.

## Flight extraction (date/time, route, airline)

This repository now includes `extract_flights.py`, which exports one row per flight with:

- `datetime_utc` (departure timestamp)
- `departure_iata` + `arrival_iata` (IATA, 3 letters)
- `airline` (inferred from callsign prefix + airline reference data)

### Data sources used

- Flight records: [OpenSky flights/departure API](https://openskynetwork.github.io/opensky-api/rest.html)
- Airline ICAO mapping: [OpenFlights airlines.dat](https://openflights.org/data)

Note: OpenSky endpoints work with ICAO airport identifiers internally; this script converts airport codes to IATA in the exported dataset.

### Run example

```bash
python -m pip install -r requirements.txt
python extract_flights.py --start-date 2026-04-01 --end-date 2026-04-03 --airport-limit 100 --output flights_sample.csv
```

Useful timeout options:

```bash
python extract_flights.py --start-date 2026-04-01 --end-date 2026-04-03 --request-timeout-seconds 20 --stage-timeout-seconds 60 --max-run-seconds 900
```

When run, extractor also downloads and saves:
- `airports.csv`
- `airlines.csv`

If OpenSky rejects unauthenticated requests, run with credentials:

```bash
python extract_flights.py --start-date 2026-04-01 --end-date 2026-04-03 --opensky-username YOUR_USER --opensky-password YOUR_PASS
```

### Important note about "all flights"

There is no truly free unlimited global source for complete historical flight records.  
This script is a practical starter that can scale in chunks (date windows + airport batches), but full global coverage typically requires a paid provider.
