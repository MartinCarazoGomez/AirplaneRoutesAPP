import argparse
import csv
import datetime as dt
import io
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import requests


AIRPORTS_URL = "https://raw.githubusercontent.com/davidmegginson/ourairports-data/main/airports.csv"
AIRLINES_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airlines.dat"
OPENSKY_DEPARTURES_URL = "https://opensky-network.org/api/flights/departure"
COMMERCIAL_TYPES = {"large_airport", "medium_airport", "small_airport"}


def log_event(stage: str, message: str) -> None:
    now = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    print(f"[{now}] [{stage}] {message}")


def assert_duration(stage: str, started_at: float, max_seconds: float) -> float:
    elapsed = time.perf_counter() - started_at
    if elapsed > max_seconds:
        raise TimeoutError(
            f"{stage} exceeded time limit: {elapsed:.2f}s > {max_seconds:.2f}s."
        )
    return elapsed


def parse_iso_date(date_str: str) -> dt.datetime:
    return dt.datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=dt.UTC)


def load_commercial_airports(
    limit: int,
    local_csv_path: Path,
    request_timeout_seconds: float,
    stage_timeout_seconds: float,
) -> tuple[list[str], dict[str, str]]:
    net_started = time.perf_counter()
    log_event("NET", f"Downloading airport database from {AIRPORTS_URL}")
    response = requests.get(AIRPORTS_URL, timeout=request_timeout_seconds)
    response.raise_for_status()
    net_elapsed = time.perf_counter() - net_started
    log_event("NET", f"Airport database downloaded in {net_elapsed:.2f}s")
    file_started = time.perf_counter()
    local_csv_path.parent.mkdir(parents=True, exist_ok=True)
    local_csv_path.write_text(response.text, encoding="utf-8")
    file_elapsed = assert_duration(
        "Airport CSV local write", file_started, stage_timeout_seconds
    )
    log_event("FILE", f"Saved airport CSV to {local_csv_path} in {file_elapsed:.2f}s")

    parse_started = time.perf_counter()
    airports = pd.read_csv(
        io.StringIO(response.text),
        usecols=["ident", "iata_code", "type", "scheduled_service"],
        low_memory=False,
    )
    parse_elapsed = assert_duration(
        "Airport CSV parse", parse_started, stage_timeout_seconds
    )
    log_event("PARSE", f"Airport CSV parsed in {parse_elapsed:.2f}s")

    filtered = airports[
        airports["type"].isin(COMMERCIAL_TYPES)
        & (airports["scheduled_service"].fillna("").str.lower() == "yes")
        & airports["ident"].fillna("").str.upper().str.match(r"^[A-Z]{4}$")
        & airports["iata_code"].fillna("").str.upper().str.match(r"^[A-Z]{3}$")
    ]

    filtered = filtered.copy()
    filtered["ident"] = filtered["ident"].str.upper()
    filtered["iata_code"] = filtered["iata_code"].str.upper()
    filtered = filtered.drop_duplicates(subset=["ident"])

    # Prefer larger airports first to increase useful hit rate.
    type_rank = {"large_airport": 0, "medium_airport": 1, "small_airport": 2}
    filtered["_type_rank"] = filtered["type"].map(type_rank).fillna(99)
    filtered.sort_values(by=["_type_rank", "ident"], inplace=True)

    # Build a global mapping to convert all departure/arrival ICAO to IATA.
    icao_to_iata = dict(zip(filtered["ident"].tolist(), filtered["iata_code"].tolist()))

    idents = filtered["ident"].tolist()
    if limit > 0:
        idents = idents[:limit]
    return idents, icao_to_iata


def load_airline_icao_map(
    local_csv_path: Path,
    request_timeout_seconds: float,
    stage_timeout_seconds: float,
) -> dict[str, str]:
    net_started = time.perf_counter()
    log_event("NET", f"Downloading airline database from {AIRLINES_URL}")
    response = requests.get(AIRLINES_URL, timeout=request_timeout_seconds)
    response.raise_for_status()
    net_elapsed = time.perf_counter() - net_started
    log_event("NET", f"Airline database downloaded in {net_elapsed:.2f}s")
    file_started = time.perf_counter()
    local_csv_path.parent.mkdir(parents=True, exist_ok=True)
    local_csv_path.write_text(response.text, encoding="utf-8")
    file_elapsed = assert_duration(
        "Airline CSV local write", file_started, stage_timeout_seconds
    )
    log_event("FILE", f"Saved airline CSV to {local_csv_path} in {file_elapsed:.2f}s")

    parse_started = time.perf_counter()
    reader = csv.reader(response.text.splitlines(), delimiter=",", quotechar='"')
    airline_by_icao: dict[str, str] = {}
    for row in reader:
        if len(row) < 8:
            continue
        name = row[1].strip() if row[1] else ""
        icao = row[4].strip().upper() if row[4] else ""
        active = row[7].strip().upper() if row[7] else ""

        if not name or not icao or icao == "\\N":
            continue
        if active not in {"Y", "N"}:
            continue
        if icao not in airline_by_icao:
            airline_by_icao[icao] = name
    parse_elapsed = assert_duration(
        "Airline CSV parse", parse_started, stage_timeout_seconds
    )
    log_event("PARSE", f"Airline CSV parsed in {parse_elapsed:.2f}s")
    return airline_by_icao


def infer_airline_name(callsign: str, airline_by_icao: dict[str, str]) -> str:
    callsign = (callsign or "").strip().upper()
    if len(callsign) < 3:
        return "Unknown"
    icao_prefix = callsign[:3]
    return airline_by_icao.get(icao_prefix, "Unknown")


def query_departures(
    airport_icao: str,
    begin_unix: int,
    end_unix: int,
    auth: Optional[tuple[str, str]],
    request_timeout_seconds: float,
    stage_timeout_seconds: float,
) -> list[dict]:
    started = time.perf_counter()
    log_event(
        "NET",
        f"Request flights/departure airport={airport_icao} begin={begin_unix} end={end_unix}",
    )
    params = {"airport": airport_icao, "begin": begin_unix, "end": end_unix}
    response = requests.get(
        OPENSKY_DEPARTURES_URL,
        params=params,
        auth=auth,
        timeout=request_timeout_seconds,
    )
    elapsed = assert_duration(
        f"OpenSky request ({airport_icao})", started, stage_timeout_seconds
    )
    log_event("NET", f"OpenSky response {response.status_code} in {elapsed:.2f}s")
    if response.status_code == 404:
        return []
    if response.status_code == 401:
        raise RuntimeError(
            "OpenSky unauthorized (401). Provide --opensky-username and "
            "--opensky-password."
        )
    if response.status_code == 403:
        raise RuntimeError(
            "OpenSky forbidden (403). Your account/token likely lacks remaining "
            "credits or this endpoint requires authenticated access."
        )
    response.raise_for_status()
    return response.json()


def daterange_utc(start: dt.datetime, end: dt.datetime):
    current = start
    while current < end:
        next_day = min(current + dt.timedelta(days=1), end)
        yield current, next_day
        current = next_day


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract flight-level data (date/time, route, airline) to CSV."
    )
    parser.add_argument(
        "--start-date",
        required=True,
        help="UTC start date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--end-date",
        required=True,
        help="UTC end date exclusive (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("flights_export.csv"),
        help="Output CSV path.",
    )
    parser.add_argument(
        "--airport-limit",
        type=int,
        default=150,
        help="How many commercial airports to query (0 = all).",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.25,
        help="Pause between OpenSky requests to reduce rate-limit issues.",
    )
    parser.add_argument(
        "--opensky-username",
        default=None,
        help="OpenSky username (recommended for larger extraction runs).",
    )
    parser.add_argument(
        "--opensky-password",
        default=None,
        help="OpenSky password.",
    )
    parser.add_argument(
        "--request-timeout-seconds",
        type=float,
        default=30.0,
        help="Timeout for each HTTP request in seconds.",
    )
    parser.add_argument(
        "--stage-timeout-seconds",
        type=float,
        default=90.0,
        help="Max allowed time for key stages and requests.",
    )
    parser.add_argument(
        "--max-run-seconds",
        type=float,
        default=1800.0,
        help="Abort extraction if total runtime exceeds this limit.",
    )
    parser.add_argument(
        "--airports-csv",
        type=Path,
        default=Path("airports.csv"),
        help="Local CSV path where downloaded airport data is saved.",
    )
    parser.add_argument(
        "--airlines-csv",
        type=Path,
        default=Path("airlines.csv"),
        help="Local CSV path where downloaded airline data is saved.",
    )
    args = parser.parse_args()

    start = parse_iso_date(args.start_date)
    end = parse_iso_date(args.end_date)
    if start >= end:
        raise ValueError("--start-date must be earlier than --end-date.")

    auth = None
    if args.opensky_username and args.opensky_password:
        auth = (args.opensky_username, args.opensky_password)

    run_started = time.perf_counter()
    log_event("START", "Flight extraction started")
    log_event("CFG", f"Date range: {args.start_date} to {args.end_date} (UTC)")
    print("Loading airports and airlines reference data...")
    airports, icao_to_iata = load_commercial_airports(
        limit=args.airport_limit,
        local_csv_path=args.airports_csv,
        request_timeout_seconds=args.request_timeout_seconds,
        stage_timeout_seconds=args.stage_timeout_seconds,
    )
    airline_by_icao = load_airline_icao_map(
        local_csv_path=args.airlines_csv,
        request_timeout_seconds=args.request_timeout_seconds,
        stage_timeout_seconds=args.stage_timeout_seconds,
    )
    print(f"Airports selected: {len(airports)}")
    log_event("DATA", f"Reference data ready (airports={len(airports):,})")

    rows: list[dict] = []
    request_count = 0

    for day_start, day_end in daterange_utc(start, end):
        begin_unix = int(day_start.timestamp())
        end_unix = int(day_end.timestamp())
        print(f"Processing UTC window: {day_start.date()} to {day_end.date()}")

        for airport in airports:
            if (time.perf_counter() - run_started) > args.max_run_seconds:
                raise TimeoutError(
                    "Extraction exceeded max runtime "
                    f"({args.max_run_seconds:.2f}s)."
                )
            try:
                flights = query_departures(
                    airport_icao=airport,
                    begin_unix=begin_unix,
                    end_unix=end_unix,
                    auth=auth,
                    request_timeout_seconds=args.request_timeout_seconds,
                    stage_timeout_seconds=args.stage_timeout_seconds,
                )
            except Exception as exc:
                print(f"Warning: failed {airport} ({day_start.date()}): {exc}")
                time.sleep(args.sleep_seconds)
                continue

            request_count += 1
            for f in flights:
                dep = f.get("estDepartureAirport")
                arr = f.get("estArrivalAirport")
                first_seen = f.get("firstSeen")
                callsign = (f.get("callsign") or "").strip()

                if not dep or not arr or first_seen is None:
                    continue

                dep_iata = icao_to_iata.get(dep.upper())
                arr_iata = icao_to_iata.get(arr.upper())
                if not dep_iata or not arr_iata:
                    continue

                departure_dt = dt.datetime.fromtimestamp(first_seen, tz=dt.UTC)
                rows.append(
                    {
                        "datetime_utc": departure_dt.isoformat(),
                        "departure_iata": dep_iata,
                        "arrival_iata": arr_iata,
                        "airline": infer_airline_name(callsign, airline_by_icao),
                        "callsign": callsign,
                    }
                )

            time.sleep(args.sleep_seconds)

    out = pd.DataFrame(
        rows,
        columns=[
            "datetime_utc",
            "departure_iata",
            "arrival_iata",
            "airline",
            "callsign",
        ],
    )
    out = out.drop_duplicates(
        subset=["datetime_utc", "departure_iata", "arrival_iata", "callsign"]
    )
    if not out.empty:
        out.sort_values(by=["datetime_utc", "departure_iata"], inplace=True)

    write_started = time.perf_counter()
    log_event("FILE", f"Writing CSV to {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output, index=False)
    write_elapsed = assert_duration(
        "CSV write", write_started, args.stage_timeout_seconds
    )
    log_event("FILE", f"CSV written in {write_elapsed:.2f}s")

    print(f"Requests made: {request_count}")
    print(f"Flights exported: {len(out)}")
    print(f"Saved CSV: {args.output.resolve()}")
    if request_count == 0:
        print(
            "Note: no successful OpenSky requests. This usually means credentials "
            "or API credits are required."
        )


if __name__ == "__main__":
    main()
