"""Build the static data files the GitHub Pages site reads.

Run from the project folder:

    python export_site_data.py

This reuses the loaders in app.py. It reads the local airport, route, and
airline files plus the schedule pickle, and writes JSON under docs/data.
The large parquet and CSV flight files are not copied.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

import app as atlas


WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _clean(value: object) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    return text or None


def _parse_airlines(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    ref = pd.read_csv(
        __import__("io").StringIO(text),
        header=None,
        names=["airline_id", "name", "alias", "iata", "icao", "callsign", "country", "active"],
        usecols=["name", "iata", "icao"],
        na_values=["\\N"],
        dtype="string",
    )
    ref["name"] = ref["name"].fillna("").str.strip()
    ref["iata"] = ref["iata"].fillna("").str.upper().str.strip()
    ref["icao"] = ref["icao"].fillna("").str.upper().str.strip()
    code_to_name: dict[str, str] = {}
    for row in ref.itertuples(index=False):
        name = row.name
        if not name:
            continue
        if row.iata and row.iata != "\\N":
            code_to_name[row.iata] = name
        if row.icao and row.icao != "\\N":
            code_to_name[row.icao] = name
    return code_to_name


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    atlas.log_event("FILE", f"Wrote {path} ({path.stat().st_size / 1_048_576:.2f} MB)")


def _compact_days(per_day: dict) -> str:
    parts: list[str] = []
    for weekday in WEEKDAYS:
        times = per_day.get(weekday) or []
        if times:
            parts.append(weekday + "=" + ",".join(str(t) for t in times))
    return ";".join(parts)


def export_site(out_dir: Path) -> None:
    root = Path(__file__).resolve().parent
    airports = pd.read_csv(root / "airports.csv", low_memory=False)
    routes = pd.read_csv(root / "routes.csv", low_memory=False)
    for column in ("airline", "source_iata", "dest_iata"):
        routes[column] = routes[column].fillna("").astype(str).str.upper()
    code_to_name = _parse_airlines(root / "airlines.csv")

    airports = atlas.filter_airports_with_commercial_routes(airports, routes)
    routes_by_source = atlas.build_routes_lookup(airports, routes)
    airports = atlas.attach_hub_tiers(airports, routes_by_source)
    route_to_airlines = atlas.build_route_airlines_lookup(airports, routes, code_to_name)
    (
        _airline_routes,
        _airline_airports,
        airline_options,
    ) = atlas.build_airline_route_indexes(airports, routes, code_to_name)

    flights_path = root / "flights_history_filtered.parquet"
    if not flights_path.exists():
        flights_path = root / "2026_Q3_detailed_github.parquet"
    route_schedule = atlas.load_observed_flights_schedule(
        flights_path,
        airports=airports,
        code_to_airline_name=code_to_name,
        cache_csv=root / "flights_export.csv",
        schedule_cache=root / "flights_schedule_cache.pkl",
    )

    name_to_index = {name: index for index, name in enumerate(airline_options)}
    links: dict[str, dict[str, list[int]]] = {}
    for src, dsts in routes_by_source.items():
        bucket: dict[str, list[int]] = {}
        for dst in dsts:
            names = sorted(route_to_airlines.get((src, dst), ()))
            bucket[dst] = [name_to_index[name] for name in names if name in name_to_index]
        links[src] = bucket

    airport_rows = []
    for row in airports.itertuples(index=False):
        airport_rows.append(
            {
                "iata": str(row.iata_code),
                "lon": round(float(row.longitude_deg), 6),
                "lat": round(float(row.latitude_deg), 6),
                "tier": int(row.hub_tier),
                "name": _clean(row.name) or str(row.iata_code),
                "mun": _clean(row.municipality),
                "country": _clean(row.iso_country),
                "label": _clean(getattr(row, "label", None))
                or f"{row.name} ({row.iata_code})",
            }
        )

    myid = atlas.resolve_myid_travel_airlines(airline_options)
    asian = atlas.resolve_asian_myid_airlines(airline_options)
    meta = {
        "airports": len(airport_rows),
        "routeAirports": len(links),
        "airlines": len(airline_options),
        "schedules": len(route_schedule),
        "myid": myid,
        "asianMyid": asian,
    }

    data_dir = out_dir / "data"
    schedule_dir = data_dir / "schedule"
    if schedule_dir.exists():
        for old in schedule_dir.glob("*.json"):
            old.unlink()

    _write(data_dir / "airports.json", airport_rows)
    _write(data_dir / "network.json", {"airlines": airline_options, "links": links})
    _write(data_dir / "meta.json", meta)

    shards: dict[str, dict[str, dict[str, str]]] = {}
    for key, airlines in route_schedule.items():
        if not isinstance(key, tuple) or len(key) != 2:
            continue
        dep, arr = str(key[0]).upper(), str(key[1]).upper()
        if len(dep) < 1:
            continue
        compact: dict[str, str] = {}
        if isinstance(airlines, dict):
            for airline_name, per_day in airlines.items():
                if not isinstance(per_day, dict):
                    continue
                spec = _compact_days(per_day)
                if spec:
                    compact[str(airline_name)] = spec
        if compact:
            shards.setdefault(dep[0], {})[f"{dep}|{arr}"] = compact

    for letter, payload in sorted(shards.items()):
        _write(schedule_dir / f"{letter}.json", payload)

    atlas.log_event(
        "DATA",
        f"Exported {len(airport_rows):,} airports, {len(links):,} origins, "
        f"{len(airline_options):,} airlines, {len(route_schedule):,} schedules "
        f"in {len(shards)} schedule files.",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Export JSON for the static Airways site.")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("docs"),
        help="Site folder that will contain data/ (default: docs).",
    )
    args = parser.parse_args()
    export_site(args.out)


if __name__ == "__main__":
    main()
