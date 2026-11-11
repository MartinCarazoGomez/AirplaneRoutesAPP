"""One-shot builder: normalize local parquet flight history into flights_export.csv."""

from pathlib import Path

import pandas as pd

from app import (
    AIRLINES_URL,
    DATA_URL,
    DEFAULT_FLIGHTS_CACHE_CSV,
    DEFAULT_FLIGHTS_PARQUET,
    DEFAULT_FLIGHTS_PARQUET_FULL,
    load_airlines_reference,
    load_commercial_airports,
    load_observed_flights_schedule,
    log_event,
)


def main() -> None:
    parquet = (
        DEFAULT_FLIGHTS_PARQUET
        if DEFAULT_FLIGHTS_PARQUET.exists()
        else DEFAULT_FLIGHTS_PARQUET_FULL
    )
    if not parquet.exists():
        raise SystemExit(f"Missing parquet: {parquet.resolve()}")
    log_event("FILE", f"Using flight history source {parquet}")

    # Force rebuild even if an old cache exists.
    cache = DEFAULT_FLIGHTS_CACHE_CSV
    if cache.exists():
        cache.unlink()
        log_event("FILE", f"Removed old cache {cache}")

    airports = load_commercial_airports(
        DATA_URL,
        local_csv_path=Path("airports.csv"),
        request_timeout_seconds=60,
        stage_timeout_seconds=120,
    )
    code_to_airline_name = load_airlines_reference(
        AIRLINES_URL,
        local_csv_path=Path("airlines.csv"),
        request_timeout_seconds=60,
        stage_timeout_seconds=120,
    )
    schedule = load_observed_flights_schedule(
        parquet,
        airports=airports,
        code_to_airline_name=code_to_airline_name,
        cache_csv=cache,
    )
    log_event("DATA", f"Observed route schedules: {len(schedule):,}")
    if cache.exists():
        rows = sum(1 for _ in open(cache, encoding="utf-8")) - 1
        log_event("FILE", f"Cache rows: {rows:,} ({cache.resolve()})")
        sample = pd.read_csv(cache, nrows=5)
        print(sample.to_string(index=False))


if __name__ == "__main__":
    main()
