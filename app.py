import argparse
import ast
import io
import json
import math
import pickle
import re
import time
from collections import OrderedDict
from datetime import datetime, UTC
from functools import lru_cache
from pathlib import Path

from dash import ALL, Dash, Input, Output, State, ctx, dcc, html, no_update
import pandas as pd
import requests


DATA_URL = "https://raw.githubusercontent.com/davidmegginson/ourairports-data/main/airports.csv"
# Primary routes source (newer, weekly-updated)
ROUTES_URL = "https://raw.githubusercontent.com/Jonty/airline-route-data/main/airline_routes.json"
# Fallback routes source (legacy, historical snapshot)
# ROUTES_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/routes.dat"
ROUTES_FALLBACK_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/routes.dat"
AIRLINES_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airlines.dat"
# ADS-B derived quarterly flight history (local copy in project folder).
DEFAULT_FLIGHTS_PARQUET_FULL = Path("2026_Q3_detailed_github.parquet")
DEFAULT_FLIGHTS_PARQUET = Path("flights_history_filtered.parquet")
DEFAULT_FLIGHTS_CACHE_CSV = Path("flights_export.csv")
DEFAULT_FLIGHTS_SCHEDULE_CACHE = Path("flights_schedule_cache.pkl")
_AIRPORT_TOKEN_RE = re.compile(r"'([A-Z0-9]{3,4})'")
_VALIDATION_ROUTE_RE = re.compile(r"^([A-Z0-9]{3,4})-([A-Z0-9]{3,4})$")

# Display names used for flight-history cleaning (mapped to ICAO below).
FLIGHT_HISTORY_AIRLINE_LABELS: tuple[str, ...] = (
    "Aegean Airlines",
    "Aer Lingus",
    "Aeroflot Russian Airlines",
    "Aerolíneas Argentinas",
    "Aeroméxico",
    "Air Arabia",
    "Air Astana",
    "Air Baltic",
    "Air Calédonie",
    "Air Canada",
    "Air Caraïbes",
    "Air Corsica",
    "Air Côte d'Ivoire",
    "Air Dolomiti",
    "Air Europa",
    "Air France",
    "Air Greenland",
    "Air India",
    "Air India Express",
    "Air Inuit",
    "Air Macau",
    "Air Mauritius",
    "Air New Zealand",
    "Air Nostrum",
    "Air Serbia",
    "Air Seychelles",
    "Air Tahiti Nui",
    "Air Tindi",
    "Air Transat",
    "Aircalin",
    "Alaska Airlines",
    "All Nippon Airways",
    "Allegiant Air",
    "American Airlines",
    "Arajet",
    "Arkia",
    "Asiana Airlines",
    "ASL Airlines France",
    "Austrian Airlines",
    "Avelo Airlines",
    "Avianca",
    "Azul Linhas Aéreas",
    "Bahamasair",
    "BermudAir",
    "Binter Canarias",
    "Blue Air",
    "Braathens Regional Airlines",
    "British Airways",
    "Brussels Airlines",
    "Cabo Verde Airlines",
    "Calm Air",
    "Canadian North",
    "Canaryfly",
    "Cape Air",
    "Cathay Pacific",
    "Cayman Airways",
    "China Airlines",
    "CityJet",
    "Condor",
    "Contour Airlines",
    "Copa Airlines",
    "Corsair International",
    "Croatia Airlines",
    "Danish Air Transport",
    "Delta Air Lines",
    "EcoJet",
    "EgyptAir",
    "El Al Israel Airlines",
    "Emirates",
    "Estelar Airlines",
    "Ethiopian Airlines",
    "Etihad Airways",
    "Eurowings",
    "Discover Airlines",
    "EVA Air",
    "Fiji Airways",
    "Finnair",
    "FitsAir",
    "flydubai",
    "French Bee",
    "GOL Linhas Aéreas",
    "Hawaiian Airlines",
    "Helvetic Airways",
    "Hong Kong Airlines",
    "HK Express",
    "Iberia Express",
    "Icelandair",
    "IndiGo",
    "Iran Air",
    "Israir Airlines",
    "ITA Airways",
    "Japan Airlines",
    "JetBlue",
    "JetSuite",
    "Kenya Airways",
    "KLM",
    "KM Malta Airlines",
    "Korean Air",
    "Kuwait Airways",
    "LATAM Airlines",
    "Link Airways",
    "Loganair",
    "LOT Polish Airlines",
    "Lufthansa",
    "Luxair",
    "Malaysia Airlines",
    "Mesa Airlines",
    "Middle East Airlines",
    "NAS Aviation",
    "Norse Atlantic Airways",
    "Norwegian Air Shuttle",
    "Olympic Air",
    "Oman Air",
    "Pakistan International Airlines",
    "Pegasus Airlines",
    "Philippine Airlines",
    "Porter Airlines",
    "Qantas",
    "Qatar Airways",
    "Ravn Alaska",
    "Republic Airways",
    "Royal Air Maroc",
    "Royal Brunei Airlines",
    "Royal Jordanian",
    "SalamAir",
    "SAS Scandinavian Airlines",
    "Azores Airlines",
    "Saudia",
    "Scenic Airlines",
    "S7 Airlines",
    "SKY Airline",
    "Skyside",
    "SkyWest Airlines",
    "Smartwings",
    "South African Airways",
    "Southwest Airlines",
    "SriLankan Airlines",
    "STARLUX Airlines",
    "SunExpress",
    "Swiss International Air Lines",
    "TACA International Airlines",
    "TACA Peru",
    "TAM Airlines",
    "TAP Air Portugal",
    "TAROM",
    "Tigerair Taiwan",
    "Transavia",
    "Transavia France",
    "Transwest Air",
    "TUIfly",
    "Tunisair",
    "Turkish Airlines",
    "UNI Air",
    "United Airlines",
    "Vietnam Airlines",
    "Virgin Atlantic",
    "Virgin Australia",
    "Vistara",
    "Viva Aerobus",
    "Volotea",
    "Vueling",
    "Wasaya Airways",
    "WestJet",
    "Widerøe",
    "Wingo",
)

# ICAO operator codes observed/known for the labels above (ADS-B Airline column).
FLIGHT_HISTORY_ICAO_ALLOWLIST: frozenset[str] = frozenset(
    {
        "AAL",  # American Airlines
        "AAR",  # Asiana Airlines
        "AAY",  # Allegiant Air
        "ABS",  # Transwest Air
        "ABY",  # Air Arabia
        "ACA",  # Air Canada
        "ACI",  # Aircalin
        "AEA",  # Air Europa
        "AEE",  # Aegean Airlines
        "AFL",  # Aeroflot
        "AFR",  # Air France
        "AIC",  # Air India
        "AIE",  # Air Inuit
        "AIZ",  # Arkia
        "ALK",  # SriLankan Airlines
        "AMC",  # Air Malta / KM Malta heritage
        "AMU",  # Air Macau
        "AMX",  # Aeroméxico
        "ANA",  # All Nippon Airways
        "ANE",  # Air Nostrum
        "ANZ",  # Air New Zealand
        "ARG",  # Aerolíneas Argentinas
        "ARJ",  # Arajet
        "ASA",  # Alaska Airlines
        "ASH",  # Mesa Airlines
        "ASL",  # Air Serbia
        "AUA",  # Austrian Airlines
        "AVA",  # Avianca
        "AXB",  # Air India Express
        "AZU",  # Azul
        "BAW",  # British Airways
        "BCY",  # CityJet
        "BDA",  # BermudAir
        "BEL",  # Brussels Airlines
        "BHS",  # Bahamasair
        "BRX",  # Braathens Regional
        "BTI",  # Air Baltic
        "CAL",  # China Airlines
        "CAV",  # Calm Air
        "CAY",  # Cayman Airways
        "CCM",  # Air Corsica
        "CFG",  # Condor
        "CJT",  # Contour / related regional ops in dataset
        "CMP",  # Copa Airlines
        "CNF",  # Canaryfly
        "CPA",  # Cathay Pacific
        "CRK",  # Hong Kong Airlines
        "CRL",  # Corsair International
        "CTN",  # Croatia Airlines
        "DAL",  # Delta Air Lines
        "DLA",  # Air Dolomiti
        "DLH",  # Lufthansa
        "DTR",  # Danish Air Transport
        "ECJ",  # EcoJet
        "EIN",  # Aer Lingus
        "ELY",  # El Al
        "ETD",  # Etihad Airways
        "ETH",  # Ethiopian Airlines
        "ETR",  # Estelar
        "EVA",  # EVA Air
        "EWG",  # Eurowings
        "EXV",  # FitsAir
        "FBU",  # French Bee
        "FDB",  # flydubai
        "FIN",  # Finnair
        "FJI",  # Fiji Airways
        "FPO",  # ASL Airlines France
        "FWI",  # Air Caraïbes
        "GLO",  # GOL
        "GRL",  # Air Greenland
        "HAL",  # Hawaiian Airlines
        "HKE",  # HK Express
        "HLF",  # TUIfly (Hapag)
        "HVN",  # Vietnam Airlines
        "IBB",  # Binter Canarias
        "IBS",  # Iberia Express
        "ICE",  # Icelandair
        "IGO",  # IndiGo
        "IRA",  # Iran Air
        "ISR",  # Israir
        "ITY",  # ITA Airways
        "JAL",  # Japan Airlines
        "JBU",  # JetBlue
        "JSX",  # JetSuiteX
        "KAC",  # Kuwait Airways
        "KAL",  # Korean Air
        "KAP",  # Cape Air
        "KLC",  # KLM Cityhopper
        "KLM",  # KLM
        "KMM",  # KM Malta Airlines
        "KQA",  # Kenya Airways
        "KZR",  # Air Astana
        "LAN",  # LATAM Chile
        "LAP",  # LATAM Paraguay
        "LGL",  # Luxair
        "LNE",  # LATAM Ecuador
        "LOG",  # Loganair
        "LOT",  # LOT Polish Airlines
        "LPE",  # LATAM Peru
        "MAS",  # Malaysia Airlines
        "MAU",  # Air Mauritius
        "MEA",  # Middle East Airlines
        "MPE",  # Canadian North
        "MSR",  # EgyptAir
        "NAX",  # Norwegian Air Shuttle
        "NBT",  # Norse Atlantic
        "NSS",  # NAS Aviation (best-effort)
        "OAL",  # Olympic Air
        "OAW",  # Helvetic Airways
        "OCN",  # Discover Airlines
        "OMA",  # Oman Air
        "OMS",  # SalamAir
        "PAL",  # Philippine Airlines
        "PGT",  # Pegasus Airlines
        "PIA",  # Pakistan International Airlines
        "POE",  # Porter Airlines
        "QFA",  # Qantas
        "QTR",  # Qatar Airways
        "RAM",  # Royal Air Maroc
        "RBA",  # Royal Brunei Airlines
        "RJA",  # Royal Jordanian
        "ROT",  # TAROM
        "RPA",  # Republic Airways
        "RPB",  # Wingo
        "RSP",  # JetSuite
        "RVF",  # Ravn Alaska
        "RVH",  # Ravn Alaska variant
        "RZO",  # Azores Airlines
        "SAA",  # South African Airways
        "SAS",  # SAS
        "SBI",  # S7 Airlines
        "SCE",  # Scenic Airlines
        "SCW",  # Braathens Regional / Malmö
        "SEY",  # Air Seychelles
        "SJX",  # STARLUX Airlines
        "SKU",  # SKY Airline
        "SKW",  # SkyWest Airlines
        "SVA",  # Saudia
        "SWA",  # Southwest Airlines
        "SWR",  # Swiss
        "SXS",  # SunExpress
        "TAI",  # TACA International
        "TAM",  # TAM / LATAM Brasil
        "TAP",  # TAP Air Portugal
        "TAR",  # Tunisair
        "TCV",  # Cabo Verde Airlines
        "THT",  # Air Tahiti Nui
        "THY",  # Turkish Airlines
        "TIN",  # Air Tindi
        "TPC",  # Air Calédonie
        "TPU",  # TACA Peru
        "TRA",  # Transavia
        "TSC",  # Air Transat
        "TTW",  # Tigerair Taiwan
        "TUI",  # TUIfly
        "TVF",  # Transavia France
        "TVS",  # Smartwings
        "UAE",  # Emirates
        "UAL",  # United Airlines
        "UIA",  # UNI Air
        "VIR",  # Virgin Atlantic
        "VIV",  # Viva Aerobus
        "VLG",  # Vueling
        "VOE",  # Volotea
        "VOZ",  # Virgin Australia
        "VRE",  # Air Côte d'Ivoire
        "VTI",  # Vistara
        "VXP",  # Avelo Airlines
        "WIF",  # Widerøe
        "WJA",  # WestJet
        "WSG",  # Wasaya Airways
    }
)

MAP_STYLE_TOKENS = {
    "night": "carto-darkmatter",
    "day": "carto-positron",
    "sat": "carto-voyager",
}
# (max km, core color, glow color) — short hops through ultra-long haul.
ROUTE_BANDS: tuple[tuple[float, str, str], ...] = (
    (700.0, "#fbbf24", "rgba(251,191,36,0.22)"),
    (2000.0, "#7dd3fc", "rgba(125,211,252,0.20)"),
    (5000.0, "#2dd4bf", "rgba(45,212,191,0.18)"),
    (1.0e9, "#d8b4fe", "rgba(216,180,254,0.22)"),
)

# User-defined MyID travel preset (matched to route dataset airline display names at runtime).
MYID_TRAVEL_AIRLINE_LABELS_RAW: tuple[str, ...] = tuple(
    line.strip()
    for line in """
Iberia airlines
AEGEAN AIRLINES
AER LINGUS
AEROFLOT RUSSIAN AIRLINES
AEROLÍNEAS ARGENTINAS
AEROMEXICO
AIR ARABIA
AIR BALTIC CORPORATION
AIR CALEDONIE
AIR CANADA
AIR CARAIBES
AIR CORSICA
AIR COTE D'IVOIRE
AIR DOLOMITI
AIR EUROPA
AIR FRANCE
AIR GREENLAND
AIR INDIA
AIR INUIT
AIR MACAU
AIR MAURITIUS
AIR NEW ZEALAND
AIR NOSTRUM
AIR SERBIA
AIR SEYCHELLES
AIR TAHITI NUI
AIR TINDI
AIR TRANSAT
AIRCALIN
ALASKA AIRLINES
ALL NIPPON AIRWAYS
ALLEGIANT AIR
AMERICAN AIRLINES
ARAJET
ARKIA
ASIANA AIRL
ASL AIRLINES FRANCE
AUSTRIAN AIRLINES
AVELO AIRLINES
AVIANCA
AZUL LINHAS AEREAS
BAHAMASAIR
BINTER CANARIAS-ZED
BLUE AIR
BRAATHENS REGIONAL AIR
BRITISH AIRWAYS
BRUSSELS
CABO VERDE AIRLINES
CANADIAN NORTH
CANARY FLY
CAPE AIR
CATHAY PACIFIC
CAYMAN AIRWAYS
CHINA AIRLINES
CITYJET
CONDOR
CONTOUR AIRLINES
COPA AIRLINES
CORSAIR INTERNATIONAL
CROATIA AIRLINES
DANISH AIR TRANSPORT
DELTA AIRLINES
ECOJET
EGYPTAIR
EL AL ISRAEL
EMIRATES
ESTELAR AIR
ETHIOPIAN AIRLINES
ETIHAD AIRWAYS
EUROWINGS
EUROWINGS DISCOVER
EVA AIRWAYS
FIJI AIRWAYS
FINNAIR
FITS AIR
FLYDUBAI
FRENCH BEE
GOL AIR TRANSPORT
HAWAIIAN AIRLINES
HELVETIC AIRWAYS
HONG KONG AIRLINES LIMITED
HONG KONG EXPRESS
IBERIA EXPRESS
ICELANDAIR
INDIGO
IRAN AIR
ISRAIR AIRLINES
ITA AIRLINES
JAL
JETBLUE
JETSUITE
KENYA AIRWAYS
KLM
KM MALTA AIRLINES
KOREAN AIR
KUWAIT AIRWAYS
LACSA
LATAM
LINK AIRWAYS
LOGAN AIR
LOT
LUFTHANSA
LUXAIR
MALAYSIA
MESA AIRLINES
MIDDLE EAST AIRLINES
NORSE ATLANTIC AIRWAYS
NORWEGIAN
OLYMPIC AIRLINES
OMAN AIR
PAKISTAN INT AIRLINES
PEGASUS
PHILIPPINE AIRLINES
PORTER AIRLINES INC
QANTAS
QATAR AIRWAYS
RAVN ALASKA
REPUBLIC AIRLINES
ROYAL AIR MAROC
ROYAL BRUNEI AIRLINES
ROYAL JORDANIAN
SALAM AIR
SAS
SATA INTERNATIONAL
SAUDI ARABIAN AIRLINES
SCENIC AIRLINES
Siberia Airlines
SKY AIRLINES
SKYWEST AIRLINES
SMARTWINGS
SOUTH AFRICAN AIRWAYS
SOUTHWEST
SPIRIT AIRLINES
SRI LANKAN AIRLINES
STARLUX AIRLINES
SUNEXPRESS
SWISS
TACA INTL AIRLINES
TACA PERU
TAM (JJ)
TAP
TAROM
TIGERAIR TAIWAN
TRANS STATES AIRLINES
TRANSAVIA AIRLINES
TRANSAVIA FRANCE
TUIFLY
TUNIS AIR
TURKISH AIRLINES
UNI AIR
UNITED AIRLINES
VIETNAM AIRLINES
VIRGIN ATLANTIC AIRWAYS
VIRGIN AUSTRALIA
VISTARA
VIVAAEROBUS
VOLOTEA
VUELING
WASAYA AIRLINES
WEST JET
Wideroe's Flyveselskap
""".strip().splitlines()
    if line.strip()
)

# Normalized user label -> normalized substring that must appear in a unique dataset airline name.
MYID_RESOLVE_HINTS: dict[str, str] = {
    "ASIANA AIRL": "ASIANA",
    "BINTER CANARIAS-ZED": "BINTER",
    "BRUSSELS": "BRUSSELS",
    "JAL": "JAPAN",
    "LACSA": "LACSA",
    "LOGAN AIR": "LOGANAIR",
    "MALAYSIA": "MALAYSIA",
    "NORWEGIAN": "NORWEGIAN",
    "OLYMPIC AIRLINES": "OLYMPIC",
    "SAS": "SCANDINAVIAN",
    "SOUTHWEST": "SOUTHWEST",
    "TAM (JJ)": "TAM",
    "WEST JET": "WESTJET",
}

ASIAN_MYID_AIRLINE_LABELS_RAW: tuple[str, ...] = (
    "KOREAN AIR",
    "ASIANA",
    "JAPAN AIRLINES",
    "ALL NIPPON AIRWAYS",
    "VIETNAM AIRLINES",
    "CATHAY PACIFIC",
    "HONG KONG EXPRESS",
    "PHILIPPINE AIRLINES",
    "MALAYSIAN AIRLINES",
    "CATHAY DRAGON",
    "JETSTAR JAPAN",
    "JETSTAR",
    "QANTAS",
    "EVA AIR",
    "STARLUX",
    "CHINA AIRLINES",
)

ASIAN_MYID_RESOLVE_HINTS: dict[str, str] = {
    "ASIANA": "ASIANA",
    "JAPAN AIRLINES": "JAPAN AIRLINES",
    "PHILIPPINE AIRLINES": "PHILIPPINE",
    "MALAYSIAN AIRLINES": "MALAYSIA",
    "CATHAY DRAGON": "DRAGON",
    "JETSTAR JAPAN": "JETSTAR JAPAN",
    "JETSTAR": "JETSTAR",
    "EVA AIR": "EVA",
    "STARLUX": "STARLUX",
}


def _norm_airline_label(s: str) -> str:
    t = " ".join(s.strip().upper().split())
    return t.replace("?", "'").replace("`", "'")


# Skip these if they appear as preset labels or as resolved dataset names (bad/missing rows).
_PRESET_SKIP_AIRLINE_NORMALIZED: frozenset[str] = frozenset({"NA", "N/A", "NULL", "\\N"})


def resolve_airline_group(
    labels_raw: tuple[str, ...],
    resolve_hints: dict[str, str],
    airline_options: list[str],
    group_name: str,
) -> list[str]:
    """Map user-defined airline labels to names present in airline_options."""
    norm_to_canon: dict[str, str] = {}
    for opt in airline_options:
        n = _norm_airline_label(opt)
        norm_to_canon.setdefault(n, opt)

    resolved: list[str] = []
    seen: set[str] = set()

    for raw in labels_raw:
        label = raw.strip()
        if not label:
            continue
        nw = _norm_airline_label(label)
        if nw in _PRESET_SKIP_AIRLINE_NORMALIZED:
            continue
        if nw in norm_to_canon:
            c = norm_to_canon[nw]
            if c not in seen:
                seen.add(c)
                resolved.append(c)
            continue

        hint = resolve_hints.get(nw)
        if hint:
            hint_u = hint.upper()
            hint_matches = [o for o in airline_options if hint_u in _norm_airline_label(o)]
            if len(hint_matches) == 1:
                c = hint_matches[0]
                if c not in seen:
                    seen.add(c)
                    resolved.append(c)
                continue
            if len(hint_matches) > 1:
                hint_matches.sort(key=lambda x: (len(x), x))
                c = hint_matches[0]
                if c not in seen:
                    seen.add(c)
                    resolved.append(c)
                continue

        candidates = [
            o
            for o in airline_options
            if nw in _norm_airline_label(o) or _norm_airline_label(o) in nw
        ]
        if len(nw) < 4 and len(candidates) > 1:
            candidates = [o for o in candidates if _norm_airline_label(o) == nw]

        if len(candidates) == 1:
            c = candidates[0]
            if c not in seen:
                seen.add(c)
                resolved.append(c)
            continue
        if len(candidates) > 1:
            narrowed = [o for o in candidates if _norm_airline_label(o).startswith(nw)]
            pick = narrowed[0] if len(narrowed) == 1 else sorted(candidates, key=lambda x: (len(x), x))[0]
            if pick not in seen:
                seen.add(pick)
                resolved.append(pick)
            continue

        log_event("WARN", f"{group_name} preset: no match for airline label {label!r}")

    return [
        x
        for x in resolved
        if _norm_airline_label(x) not in _PRESET_SKIP_AIRLINE_NORMALIZED
    ]


def resolve_myid_travel_airlines(airline_options: list[str]) -> list[str]:
    return resolve_airline_group(
        labels_raw=MYID_TRAVEL_AIRLINE_LABELS_RAW,
        resolve_hints=MYID_RESOLVE_HINTS,
        airline_options=airline_options,
        group_name="MyID travel",
    )


def resolve_asian_myid_airlines(airline_options: list[str]) -> list[str]:
    return resolve_airline_group(
        labels_raw=ASIAN_MYID_AIRLINE_LABELS_RAW,
        resolve_hints=ASIAN_MYID_RESOLVE_HINTS,
        airline_options=airline_options,
        group_name="Asian MyID",
    )


def log_event(stage: str, message: str) -> None:
    timestamp = datetime.now(UTC).isoformat(timespec="seconds")
    print(f"[{timestamp}] [{stage}] {message}")


def assert_duration(stage: str, started_at: float, max_seconds: float) -> float:
    elapsed = time.perf_counter() - started_at
    if elapsed > max_seconds:
        raise TimeoutError(
            f"{stage} exceeded time limit: {elapsed:.2f}s > {max_seconds:.2f}s."
        )
    return elapsed


def load_commercial_airports(
    url: str,
    local_csv_path: Path,
    request_timeout_seconds: float,
    stage_timeout_seconds: float,
) -> pd.DataFrame:
    """Download and filter airports to likely commercial operations."""
    started = time.perf_counter()
    log_event("NET", f"Downloading airport database from {url}")
    response = requests.get(url, timeout=request_timeout_seconds)
    response.raise_for_status()
    net_elapsed = time.perf_counter() - started
    log_event("NET", f"Airport database downloaded in {net_elapsed:.2f}s")
    parse_started = time.perf_counter()
    airports = pd.read_csv(
        io.StringIO(response.text),
        usecols=[
            "ident",
            "iata_code",
            "name",
            "latitude_deg",
            "longitude_deg",
            "type",
            "scheduled_service",
            "municipality",
            "iso_country",
        ],
        low_memory=False,
    )
    parse_elapsed = assert_duration("Airport CSV parse", parse_started, stage_timeout_seconds)
    log_event("PARSE", f"Airport CSV parsed in {parse_elapsed:.2f}s")

    filtered = airports[
        (airports["type"].fillna("").str.lower() != "heliport")
        & airports["iata_code"].fillna("").str.upper().str.match(r"^[A-Z]{3}$")
        & airports["latitude_deg"].notna()
        & airports["longitude_deg"].notna()
    ].copy()

    filtered["label"] = (
        filtered["name"]
        + " ("
        + filtered["iata_code"].str.upper()
        + ")"
        + "<br>"
        + filtered["municipality"].fillna("Unknown city")
        + ", "
        + filtered["iso_country"].fillna("Unknown country")
    )
    filtered["iata_code"] = filtered["iata_code"].str.upper()
    filtered = filtered.drop_duplicates(subset=["iata_code"]).copy()

    file_started = time.perf_counter()
    local_csv_path.parent.mkdir(parents=True, exist_ok=True)
    filtered.to_csv(local_csv_path, index=False)
    file_elapsed = assert_duration(
        "Airport CSV local write", file_started, stage_timeout_seconds
    )
    log_event(
        "FILE",
        f"Saved filtered airport CSV (no heliports) to {local_csv_path} in {file_elapsed:.2f}s",
    )
    return filtered


def load_routes(
    url: str,
    local_csv_path: Path,
    request_timeout_seconds: float,
    stage_timeout_seconds: float,
) -> pd.DataFrame:
    def _sanitize_routes(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["airline"] = df["airline"].fillna("").str.upper()
        df["source_iata"] = df["source_iata"].fillna("").str.upper()
        df["dest_iata"] = df["dest_iata"].fillna("").str.upper()
        df = df[
            df["source_iata"].str.match(r"^[A-Z]{3}$")
            & df["dest_iata"].str.match(r"^[A-Z]{3}$")
            & df["airline"].str.match(r"^[A-Z0-9-]{2,20}$")
        ].drop_duplicates(subset=["source_iata", "dest_iata", "airline"])
        return df

    def _parse_openflights_csv(text: str) -> pd.DataFrame:
        parsed = pd.read_csv(
            io.StringIO(text),
            header=None,
            names=[
                "airline",
                "airline_id",
                "source_iata",
                "source_airport_id",
                "dest_iata",
                "dest_airport_id",
                "codeshare",
                "stops",
                "equipment",
            ],
            usecols=["airline", "source_iata", "dest_iata"],
            na_values=["\\N"],
            dtype="string",
        )
        return _sanitize_routes(parsed)

    def _parse_jonty_json(text: str) -> pd.DataFrame:
        payload = json.loads(text)
        rows: list[dict[str, str]] = []
        for source_iata, airport in payload.items():
            if not isinstance(airport, dict):
                continue
            routes = airport.get("routes", [])
            if not isinstance(routes, list):
                continue
            for route in routes:
                if not isinstance(route, dict):
                    continue
                dest_iata = str(route.get("iata", "")).upper()
                carriers = route.get("carriers", [])
                if not carriers:
                    rows.append(
                        {
                            "airline": "UNKNOWN",
                            "source_iata": str(source_iata).upper(),
                            "dest_iata": dest_iata,
                        }
                    )
                    continue
                for carrier in carriers:
                    if not isinstance(carrier, dict):
                        continue
                    airline_code = str(carrier.get("iata", "")).upper().strip()
                    airline_name = str(carrier.get("name", "")).strip().upper()
                    airline = airline_code or airline_name or "UNKNOWN"
                    rows.append(
                        {
                            "airline": airline,
                            "source_iata": str(source_iata).upper(),
                            "dest_iata": dest_iata,
                        }
                    )
        parsed = pd.DataFrame(rows, columns=["airline", "source_iata", "dest_iata"])
        return _sanitize_routes(parsed)

    started = time.perf_counter()
    log_event("NET", f"Downloading routes database from {url}")
    response = requests.get(url, timeout=request_timeout_seconds)
    response.raise_for_status()
    net_elapsed = time.perf_counter() - started
    log_event("NET", f"Routes database downloaded in {net_elapsed:.2f}s")

    parse_started = time.perf_counter()
    try:
        routes = _parse_jonty_json(response.text)
        parse_elapsed = assert_duration(
            "Routes JSON parse (Jonty)", parse_started, stage_timeout_seconds
        )
        log_event("PARSE", f"Routes JSON parsed in {parse_elapsed:.2f}s")
    except Exception as exc:
        log_event(
            "WARN",
            f"Primary routes source parse failed ({exc}). Falling back to OpenFlights.",
        )
        fallback_started = time.perf_counter()
        fallback_response = requests.get(
            ROUTES_FALLBACK_URL, timeout=request_timeout_seconds
        )
        fallback_response.raise_for_status()
        routes = _parse_openflights_csv(fallback_response.text)
        parse_elapsed = assert_duration(
            "Routes CSV parse (fallback)", fallback_started, stage_timeout_seconds
        )
        log_event("PARSE", f"Fallback routes CSV parsed in {parse_elapsed:.2f}s")

    file_started = time.perf_counter()
    local_csv_path.parent.mkdir(parents=True, exist_ok=True)
    routes.to_csv(local_csv_path, index=False)
    file_elapsed = assert_duration(
        "Routes CSV local write", file_started, stage_timeout_seconds
    )
    log_event("FILE", f"Saved routes CSV to {local_csv_path} in {file_elapsed:.2f}s")
    return routes


def load_airlines_reference(
    url: str,
    local_csv_path: Path,
    request_timeout_seconds: float,
    stage_timeout_seconds: float,
) -> dict[str, str]:
    started = time.perf_counter()
    log_event("NET", f"Downloading airlines reference from {url}")
    response = requests.get(url, timeout=request_timeout_seconds)
    response.raise_for_status()
    net_elapsed = time.perf_counter() - started
    log_event("NET", f"Airlines reference downloaded in {net_elapsed:.2f}s")

    file_started = time.perf_counter()
    local_csv_path.parent.mkdir(parents=True, exist_ok=True)
    local_csv_path.write_text(response.text, encoding="utf-8")
    file_elapsed = assert_duration(
        "Airlines CSV local write", file_started, stage_timeout_seconds
    )
    log_event("FILE", f"Saved airlines CSV to {local_csv_path} in {file_elapsed:.2f}s")

    parse_started = time.perf_counter()
    ref = pd.read_csv(
        io.StringIO(response.text),
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
    for _, row in ref.iterrows():
        name = row["name"]
        if not name:
            continue
        iata = row["iata"]
        icao = row["icao"]
        if iata and iata != "\\N":
            code_to_name[iata] = name
        if icao and icao != "\\N":
            code_to_name[icao] = name

    parse_elapsed = assert_duration(
        "Airlines reference parse", parse_started, stage_timeout_seconds
    )
    log_event("PARSE", f"Airlines reference parsed in {parse_elapsed:.2f}s")
    return code_to_name


def route_curve_steps(distance_km: float) -> int:
    """Samples along a great circle so the drawn leg reads as one curve."""
    if distance_km < 700:
        return 16
    if distance_km < 2200:
        return 24
    if distance_km < 5500:
        return 36
    return 48


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    radius = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return 2.0 * radius * math.asin(min(1.0, math.sqrt(a)))


def camera_for_points(
    lons: list[float], lats: list[float]
) -> tuple[float, float, float] | None:
    """Return (lon, lat, zoom) framing the given points, dateline-safe."""
    if not lons or not lats:
        return None
    base = float(lons[0])
    shifted: list[float] = []
    for lon in lons:
        x = float(lon)
        while x - base > 180.0:
            x -= 360.0
        while x - base < -180.0:
            x += 360.0
        shifted.append(x)
    lon_c = sum(shifted) / len(shifted)
    while lon_c > 180.0:
        lon_c -= 360.0
    while lon_c < -180.0:
        lon_c += 360.0
    lat_c = sum(float(v) for v in lats) / len(lats)
    lon_span = max(shifted) - min(shifted)
    lat_span = max(float(v) for v in lats) - min(float(v) for v in lats)
    span = max(lon_span, lat_span, 0.45)
    zoom = max(1.2, min(5.6, 5.7 - math.log2(span + 0.7)))
    return lon_c, max(-62.0, min(74.0, lat_c)), zoom


@lru_cache(maxsize=180000)
def _build_wrapped_route_line_cached(
    src_lon: float,
    src_lat: float,
    dst_lon: float,
    dst_lat: float,
    steps: int = 40,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """
    Build a great-circle route polyline that follows the shortest path.

    We keep an unwrapped longitude sequence (can go beyond +/-180) so map
    rendering does not jump to the opposite side of the world on dateline routes.
    """
    lat1 = math.radians(src_lat)
    lon1 = math.radians(src_lon)
    lat2 = math.radians(dst_lat)
    lon2 = math.radians(dst_lon)

    p1 = (
        math.cos(lat1) * math.cos(lon1),
        math.cos(lat1) * math.sin(lon1),
        math.sin(lat1),
    )
    p2 = (
        math.cos(lat2) * math.cos(lon2),
        math.cos(lat2) * math.sin(lon2),
        math.sin(lat2),
    )

    dot = max(-1.0, min(1.0, p1[0] * p2[0] + p1[1] * p2[1] + p1[2] * p2[2]))
    omega = math.acos(dot)

    raw_lons: list[float] = []
    raw_lats: list[float] = []

    for i in range(steps + 1):
        t = i / steps
        if omega < 1e-12:
            x, y, z = p1
        else:
            sin_omega = math.sin(omega)
            a = math.sin((1.0 - t) * omega) / sin_omega
            b = math.sin(t * omega) / sin_omega
            x = a * p1[0] + b * p2[0]
            y = a * p1[1] + b * p2[1]
            z = a * p1[2] + b * p2[2]

        lon_deg = math.degrees(math.atan2(y, x))
        lat_deg = math.degrees(math.atan2(z, math.hypot(x, y)))
        raw_lons.append(lon_deg)
        raw_lats.append(lat_deg)

    # Unwrap longitudes to keep each step continuous (minimal jump path).
    unwrapped_lons: list[float] = [raw_lons[0]]
    for lon in raw_lons[1:]:
        candidate = lon
        prev = unwrapped_lons[-1]
        while (candidate - prev) > 180.0:
            candidate -= 360.0
        while (candidate - prev) < -180.0:
            candidate += 360.0
        unwrapped_lons.append(candidate)

    return tuple(float(lon) for lon in unwrapped_lons), tuple(
        float(lat) for lat in raw_lats
    )


def build_wrapped_route_line(
    src_lon: float,
    src_lat: float,
    dst_lon: float,
    dst_lat: float,
    steps: int = 40,
) -> tuple[list[float | None], list[float | None]]:
    """
    Cached wrapper for great-circle polyline generation.
    Rounds coordinates so equivalent points hit the same cache key.
    """
    lons, lats = _build_wrapped_route_line_cached(
        round(float(src_lon), 6),
        round(float(src_lat), 6),
        round(float(dst_lon), 6),
        round(float(dst_lat), 6),
        int(steps),
    )
    return list(lons), list(lats)


def sample_route_position(
    route_lon: list[float | None], route_lat: list[float | None], t: float
) -> tuple[float, float] | None:
    """Pick a point along a route polyline for arrows/flow markers."""
    if not route_lon or not route_lat:
        return None
    clean: list[tuple[float, float]] = []
    for lon, lat in zip(route_lon, route_lat):
        if lon is None or lat is None:
            continue
        clean.append((float(lon), float(lat)))
    if not clean:
        return None
    tt = max(0.0, min(1.0, t))
    idx = min(len(clean) - 1, int(tt * (len(clean) - 1)))
    return clean[idx]


def initial_bearing_deg(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Forward azimuth from (lat1, lon1) toward (lat2, lon2), degrees [0, 360)."""
    rlat1 = math.radians(lat1)
    rlat2 = math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    y = math.sin(dlon) * math.cos(rlat2)
    x = math.cos(rlat1) * math.sin(rlat2) - math.sin(rlat1) * math.cos(rlat2) * math.cos(
        dlon
    )
    deg = math.degrees(math.atan2(y, x))
    return (deg + 360.0) % 360.0


def trim_route_polyline(
    route_lon: list[float], route_lat: list[float], frac: float
) -> tuple[list[float], list[float]]:
    """Prefix of the polyline from the origin, with an interpolated tip at frac ∈ [0, 1]."""
    frac = max(0.0, min(1.0, frac))
    if not route_lon:
        return [], []
    if frac <= 0.0:
        return [route_lon[0]], [route_lat[0]]
    n = len(route_lon)
    if frac >= 1.0 or n == 1:
        return list(route_lon), list(route_lat)
    pos = frac * (n - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    t = pos - lo
    if hi <= lo:
        return [route_lon[lo]], [route_lat[lo]]
    lon_f = route_lon[lo] + t * (route_lon[hi] - route_lon[lo])
    lat_f = route_lat[lo] + t * (route_lat[hi] - route_lat[lo])
    return route_lon[: lo + 1] + [lon_f], route_lat[: lo + 1] + [lat_f]


def smoothstep01(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


def build_global_route_network_lines(
    airports: pd.DataFrame,
    routes_by_source: dict[str, set[str]],
    max_segments: int = 45000,
    steps: int = 10,
) -> tuple[list[float | None], list[float | None], int, int]:
    """
    Precompute one Scattergeo line trace (many segments separated by None) for the
    whole network. Subsamples if there are more than max_segments edges.
    Returns (lon_seq, lat_seq, total_edges_in_index, segments_drawn).
    """
    airport_by_iata = airports.set_index("iata_code")
    edges: list[tuple[str, str]] = []
    for src, dsts in routes_by_source.items():
        if src not in airport_by_iata.index:
            continue
        for dst in dsts:
            if dst in airport_by_iata.index:
                edges.append((src, dst))
    total_edges = len(edges)
    if total_edges > max_segments:
        step = max(1, total_edges // max_segments)
        edges = edges[::step]
    drawn = len(edges)
    line_lon: list[float | None] = []
    line_lat: list[float | None] = []
    for src, dst in edges:
        srow = airport_by_iata.loc[src]
        drow = airport_by_iata.loc[dst]
        rl, rlat = build_wrapped_route_line(
            float(srow["longitude_deg"]),
            float(srow["latitude_deg"]),
            float(drow["longitude_deg"]),
            float(drow["latitude_deg"]),
            steps=steps,
        )
        line_lon.extend(rl + [None])
        line_lat.extend(rlat + [None])
    return line_lon, line_lat, total_edges, drawn


_MESH_PACK: dict[int, list] = {}
# Distinct cities served. Mega is reserved for the global top of that count.
_HUB_TIER_CUTS = (
    (180, 0),  # mega
    (70, 1),  # large
    (20, 2),  # medium
    (6, 3),  # small
)  # below 6: really small


def route_neighbor_counts(routes_by_source: dict[str, set[str]]) -> dict[str, int]:
    """How many other cities each airport flies to or from."""
    neighbors: dict[str, set[str]] = {}
    for src, dsts in routes_by_source.items():
        bucket = neighbors.setdefault(src, set())
        for dst in dsts:
            bucket.add(dst)
            neighbors.setdefault(dst, set()).add(src)
    return {code: len(cities) for code, cities in neighbors.items()}


def hub_tier_for_count(route_count: int) -> int:
    for minimum, tier in _HUB_TIER_CUTS:
        if route_count >= minimum:
            return tier
    return 4


def attach_hub_tiers(
    airports: pd.DataFrame, routes_by_source: dict[str, set[str]]
) -> pd.DataFrame:
    degree = route_neighbor_counts(routes_by_source)
    out = airports.copy()
    out["route_count"] = (
        out["iata_code"].map(degree).fillna(0).astype(int)
    )
    out["hub_tier"] = out["route_count"].map(hub_tier_for_count).astype(int)
    counts = out["hub_tier"].value_counts().sort_index()
    log_event(
        "DATA",
        "Hub tiers by cities served: "
        + ", ".join(
            f"{name} {int(counts.get(tier, 0))}"
            for tier, name in (
                (0, "mega"),
                (1, "large"),
                (2, "medium"),
                (3, "small"),
                (4, "really small"),
            )
        ),
    )
    return out


def route_apex_m(distance_km: float) -> float:
    """Peak height above the surface. Logarithmic so short hops still lift and ultra-long routes stay bounded."""
    km = max(0.0, float(distance_km))
    return 90_000.0 + 110_000.0 * math.log1p(km / 220.0)


def _arch_part(part: list[list[float]], distance_km: float | None = None) -> list[list[float]]:
    if len(part) < 2:
        return part
    if distance_km is None:
        distance_km = haversine_km(part[0][1], part[0][0], part[-1][1], part[-1][0])
    apex = route_apex_m(distance_km)
    last = len(part) - 1
    arched: list[list[float]] = []
    for i, (lon, lat) in enumerate(part):
        t = 0.0 if last == 0 else i / last
        height = apex * math.sin(math.pi * t)
        arched.append([lon, lat, round(height)])
    return arched


def _line_parts(
    lons: list[float | None],
    lats: list[float | None],
    stride: int = 1,
    distance_km: float | None = None,
) -> list[list[list[float]]]:
    parts: list[list[list[float]]] = []
    current: list[list[float]] = []
    for lon, lat in zip(lons, lats):
        if lon is None or lat is None:
            if len(current) >= 2:
                parts.append(current)
            current = []
            continue
        current.append([round(float(lon), 3), round(float(lat), 3)])
    if len(current) >= 2:
        parts.append(current)
    if stride > 1:
        thinned: list[list[list[float]]] = []
        for part in parts:
            if len(part) <= 4:
                thinned.append(part)
                continue
            kept = part[::stride]
            if kept[-1] != part[-1]:
                kept.append(part[-1])
            if len(kept) >= 2:
                thinned.append(kept)
        parts = thinned
    # One continuous route keeps a single distance so a dateline split does not drop the arch.
    if distance_km is not None and len(parts) > 1:
        total = sum(len(part) for part in parts)
        apex = route_apex_m(distance_km)
        seen = 0
        arched_parts: list[list[list[float]]] = []
        for part in parts:
            arched: list[list[float]] = []
            for lon, lat in part:
                t = 0.0 if total <= 1 else seen / (total - 1)
                arched.append([lon, lat, round(apex * math.sin(math.pi * t))])
                seen += 1
            arched_parts.append(arched)
        return arched_parts
    return [_arch_part(part, distance_km) for part in parts]


def _cached_mesh(lons: list[float | None], lats: list[float | None]) -> list:
    key = id(lons)
    packed = _MESH_PACK.get(key)
    if packed is None:
        packed = _line_parts(lons, lats, stride=2)
        _MESH_PACK[key] = packed
    return packed


def _airport_markers(
    frame: pd.DataFrame, hub: str | None, dest: str | None
) -> list:
    rows = []
    for rec in frame.itertuples(index=False):
        iata = str(rec.iata_code)
        if hub and iata == hub:
            kind = 5
        elif dest and iata == dest:
            kind = 6
        else:
            kind = int(getattr(rec, "hub_tier", 4))
        rows.append(
            [
                round(float(rec.longitude_deg), 3),
                round(float(rec.latitude_deg), 3),
                iata,
                kind,
                str(rec.label),
            ]
        )
    return rows


def build_map(
    airports: pd.DataFrame,
    routes_by_source: dict[str, set[str]],
    selected_iata: str | None = None,
    selected_destination_iata: str | None = None,
    visible_iata_filter: set[str] | None = None,
    show_all_routes_mode: bool = False,
    global_route_lines_lonlat: tuple[list[float | None], list[float | None]] | None = None,
    global_route_stats: tuple[int, int] | None = None,
    highlighted_route_legs: list[tuple[str, str, int]] | None = None,
    show_selected_hub_routes: bool = True,
    show_selected_destination_highlight: bool = True,
    keep_all_airports: bool = False,
    pins: list[dict] | None = None,
    hold_camera: bool = False,
    route_to_airlines: dict[tuple[str, str], set[str]] | None = None,
    selected_airlines: list[str] | None = None,
    layover_paths: list[tuple[str, ...]] | None = None,
    map_style: str = "night",
    map_tilt: bool = True,
    view_token: str = "world",
    focus: tuple[float, float, float] | None = None,
) -> dict:
    airport_by_iata = airports.set_index("iata_code")
    airports_with_type = airports
    destinations: list[str] = []
    route_rows: list[list] = []
    airline_lookup = route_to_airlines or {}
    airline_filter = list(selected_airlines or [])

    def leg_meta(src: str, dst: str) -> dict:
        return {
            "from": src,
            "to": dst,
            "airlines": airlines_on_leg_filtered(src, dst, airline_lookup, airline_filter),
        }

    airports_for_display = airports_with_type
    if visible_iata_filter is not None:
        airports_for_display = airports_for_display[
            airports_for_display["iata_code"].isin(visible_iata_filter)
        ]

    mesh_key = "off"
    mesh_lines: list | None = None
    draw_world_mesh = (
        show_all_routes_mode
        and global_route_lines_lonlat is not None
        and (not selected_iata or keep_all_airports)
        and not highlighted_route_legs
    )
    if draw_world_mesh:
        glon, glat = global_route_lines_lonlat
        if glon and glat:
            mesh_key = str(id(glon))
            mesh_lines = _cached_mesh(glon, glat)

    if selected_iata:
        selected_iata = selected_iata.upper()
        if selected_iata in airport_by_iata.index:
            destinations = sorted(routes_by_source.get(selected_iata, set()))
            destinations = [d for d in destinations if d in airport_by_iata.index]
            if not keep_all_airports:
                visible_iata = {selected_iata, *destinations}
                if (
                    selected_destination_iata
                    and str(selected_destination_iata).upper() in airport_by_iata.index
                ):
                    visible_iata.add(str(selected_destination_iata).upper())
                airports_for_display = airports_with_type[
                    airports_with_type["iata_code"].isin(visible_iata)
                ]

    # Draw hub route lines before airport markers so connection endpoints keep type colors on top.
    hub_src_lon = 0.0
    hub_src_lat = 0.0
    if (
        selected_iata
        and selected_iata in airport_by_iata.index
        and destinations
        and show_selected_hub_routes
    ):
        src_hub = airport_by_iata.loc[selected_iata]
        hub_src_lon = float(src_hub["longitude_deg"])
        hub_src_lat = float(src_hub["latitude_deg"])
        hub_routes: list[tuple[str, list[float], list[float], float]] = []
        for dst_iata in destinations:
            drow = airport_by_iata.loc[dst_iata]
            dst_lat = float(drow["latitude_deg"])
            dst_lon = float(drow["longitude_deg"])
            km = haversine_km(hub_src_lat, hub_src_lon, dst_lat, dst_lon)
            route_lon, route_lat = build_wrapped_route_line(
                src_lon=hub_src_lon,
                src_lat=hub_src_lat,
                dst_lon=dst_lon,
                dst_lat=dst_lat,
                steps=route_curve_steps(km),
            )
            bearing = initial_bearing_deg(hub_src_lat, hub_src_lon, dst_lat, dst_lon)
            hub_routes.append((dst_iata, route_lon, route_lat, bearing))
        hub_routes.sort(key=lambda r: (r[3], r[0]))

        for _dst_iata, route_lon, route_lat, _bearing in hub_routes:
            km = haversine_km(
                float(route_lat[0]),
                float(route_lon[0]),
                float(route_lat[-1]),
                float(route_lon[-1]),
            )
            band_idx = len(ROUTE_BANDS) - 1
            for bi, (max_km, _core, _glow) in enumerate(ROUTE_BANDS):
                if km <= max_km:
                    band_idx = bi
                    break
            for part in _line_parts(route_lon, route_lat, distance_km=km):
                route_rows.append([band_idx, part, leg_meta(selected_iata, _dst_iata)])

    chosen_dest = (
        str(selected_destination_iata).upper()
        if selected_destination_iata
        and str(selected_destination_iata).upper() in airport_by_iata.index
        else None
    )
    highlight_dest = (
        chosen_dest
        if show_selected_destination_highlight
        and chosen_dest
        and selected_iata
        and chosen_dest in destinations
        else None
    )
    if highlight_dest:
        dst_row = airport_by_iata.loc[highlight_dest]
        dst_lat = float(dst_row["latitude_deg"])
        dst_lon = float(dst_row["longitude_deg"])
        route_lon, route_lat = build_wrapped_route_line(
            src_lon=hub_src_lon,
            src_lat=hub_src_lat,
            dst_lon=dst_lon,
            dst_lat=dst_lat,
            steps=route_curve_steps(
                haversine_km(hub_src_lat, hub_src_lon, dst_lat, dst_lon)
            ),
        )
        for part in _line_parts(
            route_lon,
            route_lat,
            distance_km=haversine_km(hub_src_lat, hub_src_lon, dst_lat, dst_lon),
        ):
            route_rows.append([8, part, leg_meta(selected_iata, highlight_dest)])

    if highlighted_route_legs:
        for src_iata, dst_iata, band in highlighted_route_legs:
            if src_iata not in airport_by_iata.index or dst_iata not in airport_by_iata.index:
                continue
            src_row = airport_by_iata.loc[src_iata]
            dst_row = airport_by_iata.loc[dst_iata]
            src_lat = float(src_row["latitude_deg"])
            src_lon = float(src_row["longitude_deg"])
            dst_lat = float(dst_row["latitude_deg"])
            dst_lon = float(dst_row["longitude_deg"])
            rlon, rlat = build_wrapped_route_line(
                src_lon=src_lon,
                src_lat=src_lat,
                dst_lon=dst_lon,
                dst_lat=dst_lat,
                steps=route_curve_steps(
                    haversine_km(src_lat, src_lon, dst_lat, dst_lon)
                ),
            )
            for part in _line_parts(
                rlon,
                rlat,
                distance_km=haversine_km(src_lat, src_lon, dst_lat, dst_lon),
            ):
                route_rows.append([band, part, leg_meta(src_iata, dst_iata)])

    if focus is None:
        lon, lat, zoom = 10.0, 16.0, (1.25 if map_tilt else 1.55)
    else:
        lon, lat, zoom = focus
        if map_tilt and zoom < 1.7:
            zoom = 1.25
    return {
        "style": map_style if map_style in MAP_STYLE_TOKENS else "night",
        "globe": bool(map_tilt),
        "token": view_token,
        "holdCamera": bool(hold_camera),
        "pins": pins or [],
        "layovers": _layover_hover(layover_paths or [], leg_meta),
        "focus": {
            "lon": round(float(lon), 4),
            "lat": round(float(lat), 4),
            "zoom": round(float(zoom), 3),
            "pitch": 34.0 if route_rows else 14.0,
        },
        "airports": _airport_markers(
            airports_for_display,
            selected_iata if selected_iata in airport_by_iata.index else None,
            chosen_dest if show_selected_destination_highlight else highlight_dest,
        ),
        "routes": route_rows,
        "meshKey": mesh_key,
        "mesh": mesh_lines,
    }


def _layover_hover(paths: list[tuple[str, ...]], leg_meta) -> dict[str, dict]:
    """One itinerary per layover city: both hops, or all three when the path has two stops."""
    layovers: dict[str, dict] = {}
    for path in paths:
        if len(path) == 3:
            legs = [leg_meta(path[0], path[1]), leg_meta(path[1], path[2])]
            layovers.setdefault(path[1], {"legs": legs})
        elif len(path) >= 4:
            legs = [
                leg_meta(path[i], path[i + 1]) for i in range(len(path) - 1)
            ]
            for code in path[1:-1]:
                layovers.setdefault(code, {"legs": legs})
    return layovers


def build_routes_lookup(airports: pd.DataFrame, routes: pd.DataFrame) -> dict[str, set[str]]:
    valid_iata = set(airports["iata_code"].tolist())
    scoped = routes[
        routes["source_iata"].isin(valid_iata) & routes["dest_iata"].isin(valid_iata)
    ]
    routes_by_source: dict[str, set[str]] = {}
    for src, dst in zip(scoped["source_iata"], scoped["dest_iata"]):
        routes_by_source.setdefault(src, set()).add(dst)
    return routes_by_source


def build_route_airlines_lookup(
    airports: pd.DataFrame, routes: pd.DataFrame, code_to_airline_name: dict[str, str]
) -> dict[tuple[str, str], set[str]]:
    valid_iata = set(airports["iata_code"].tolist())
    scoped = routes[
        routes["source_iata"].isin(valid_iata) & routes["dest_iata"].isin(valid_iata)
    ]
    route_to_airlines: dict[tuple[str, str], set[str]] = {}
    for _, row in scoped.iterrows():
        src = row["source_iata"]
        dst = row["dest_iata"]
        code = row["airline"]
        name = code_to_airline_name.get(code, code)
        route_to_airlines.setdefault((src, dst), set()).add(name)
    return route_to_airlines


def build_airline_route_indexes(
    airports: pd.DataFrame, routes: pd.DataFrame, code_to_airline_name: dict[str, str]
) -> tuple[dict[str, dict[str, set[str]]], dict[str, set[str]], list[str]]:
    valid_iata = set(airports["iata_code"].tolist())
    scoped = routes[
        routes["source_iata"].isin(valid_iata) & routes["dest_iata"].isin(valid_iata)
    ]

    airline_to_routes_by_source: dict[str, dict[str, set[str]]] = {}
    airline_to_connected_airports: dict[str, set[str]] = {}

    for _, row in scoped.iterrows():
        src = row["source_iata"]
        dst = row["dest_iata"]
        code = row["airline"]
        airline = code_to_airline_name.get(code, code)

        airline_to_routes_by_source.setdefault(airline, {}).setdefault(src, set()).add(dst)
        airline_to_connected_airports.setdefault(airline, set()).update([src, dst])

    airline_options = sorted(airline_to_routes_by_source.keys())
    return airline_to_routes_by_source, airline_to_connected_airports, airline_options


def merge_airline_filters(
    airline_names: list[str],
    airline_to_routes_by_source: dict[str, dict[str, set[str]]],
    airline_to_connected_airports: dict[str, set[str]],
) -> tuple[dict[str, set[str]], set[str]]:
    """Union of route maps and connected airports for multiple airline display names."""
    merged_routes: dict[str, set[str]] = {}
    merged_airports: set[str] = set()
    for name in airline_names:
        for src, dsts in airline_to_routes_by_source.get(name, {}).items():
            merged_routes.setdefault(src, set()).update(dsts)
        merged_airports.update(airline_to_connected_airports.get(name, set()))
    return merged_routes, merged_airports


def prepare_airports_for_map(airports: pd.DataFrame) -> pd.DataFrame:
    """One copy + normalized type labels; reuse for every map build to avoid per-frame DataFrame churn."""
    out = airports.copy()
    out["type"] = out["type"].fillna("").str.lower()
    return out


def build_icao_to_iata(airports: pd.DataFrame) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for ident, iata in zip(
        airports["ident"].fillna("").astype(str),
        airports["iata_code"].fillna("").astype(str),
    ):
        ident_u = ident.strip().upper()
        iata_u = iata.strip().upper()
        if re.fullmatch(r"[A-Z0-9]{3,4}", ident_u) and re.fullmatch(r"[A-Z]{3}", iata_u):
            mapping[ident_u] = iata_u
    return mapping


def _parse_airport_token_list(raw: object) -> list[str]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return []
    text = str(raw).strip()
    if not text or text in {"-", "nan", "None", "NaN"}:
        return []
    tokens = _AIRPORT_TOKEN_RE.findall(text)
    if tokens:
        return [t.upper() for t in tokens]
    # Fallback for plain ICAO strings.
    if re.fullmatch(r"[A-Za-z0-9]{3,4}", text):
        return [text.upper()]
    try:
        parsed = ast.literal_eval(text)
        if isinstance(parsed, (list, tuple)):
            return [str(x).upper() for x in parsed if str(x).strip()]
    except (SyntaxError, ValueError):
        pass
    return []


def _pick_icao_airport(
    candidates: list[str],
    preferred: str | None,
    icao_to_iata: dict[str, str],
) -> str | None:
    mapped_candidates = [c for c in candidates if c in icao_to_iata]
    if preferred and preferred in icao_to_iata:
        if not mapped_candidates or preferred in mapped_candidates:
            return preferred
    if len(mapped_candidates) == 1:
        return mapped_candidates[0]
    if preferred and preferred in mapped_candidates:
        return preferred
    if mapped_candidates:
        return mapped_candidates[0]
    return None


def _parse_validation_airports(raw: object) -> tuple[str | None, str | None]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None, None
    text = str(raw).strip().upper()
    match = _VALIDATION_ROUTE_RE.fullmatch(text)
    if not match:
        return None, None
    return match.group(1), match.group(2)


def _schedule_from_flights_frame(
    flights: pd.DataFrame,
) -> dict[tuple[str, str], dict[str, dict[str, list[str]]]]:
    required_cols = {"datetime_utc", "departure_iata", "arrival_iata", "airline"}
    if flights.empty or not required_cols.issubset(set(flights.columns)):
        return {}

    flights = flights.copy()
    flights["departure_iata"] = flights["departure_iata"].fillna("").str.upper()
    flights["arrival_iata"] = flights["arrival_iata"].fillna("").str.upper()
    flights["airline"] = flights["airline"].fillna("Unknown")
    flights["datetime_utc"] = pd.to_datetime(
        flights["datetime_utc"], utc=True, errors="coerce"
    )
    flights = flights[flights["datetime_utc"].notna()]
    flights = flights[
        flights["departure_iata"].str.match(r"^[A-Z]{3}$")
        & flights["arrival_iata"].str.match(r"^[A-Z]{3}$")
        & (flights["departure_iata"] != flights["arrival_iata"])
    ]
    if flights.empty:
        return {}

    flights["weekday"] = flights["datetime_utc"].dt.day_name().str.slice(0, 3)
    flights["hhmm"] = flights["datetime_utc"].dt.strftime("%H:%M")

    route_schedule: dict[tuple[str, str], dict[str, dict[str, list[str]]]] = {}
    grouped = flights.groupby(
        ["departure_iata", "arrival_iata", "airline", "weekday"], dropna=False
    )["hhmm"]
    for (dep, arr, airline, weekday), series in grouped:
        unique_times = sorted(set(series.tolist()))
        route_key = (dep, arr)
        route_schedule.setdefault(route_key, {}).setdefault(airline, {})[
            weekday
        ] = unique_times
    return route_schedule


def _cache_is_fresh(cache_path: Path, source_path: Path) -> bool:
    if not cache_path.exists() or not source_path.exists():
        return False
    try:
        return cache_path.stat().st_mtime >= source_path.stat().st_mtime
    except OSError:
        return False


def _load_schedule_pickle(
    path: Path,
) -> dict[tuple[str, str], dict[str, dict[str, list[str]]]] | None:
    try:
        with path.open("rb") as fh:
            payload = pickle.load(fh)
        if isinstance(payload, dict):
            return payload
    except Exception as exc:
        log_event("WARN", f"Failed reading schedule cache {path}: {exc}")
    return None


def _save_schedule_pickle(
    path: Path,
    route_schedule: dict[tuple[str, str], dict[str, dict[str, list[str]]]],
) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as fh:
            pickle.dump(route_schedule, fh, protocol=pickle.HIGHEST_PROTOCOL)
        log_event("FILE", f"Cached route schedule pickle to {path}")
    except Exception as exc:
        log_event("WARN", f"Could not write schedule cache pickle: {exc}")


def _resolve_airports_for_row(
    origin_raw: object,
    dest_raw: object,
    validation_raw: object,
    icao_to_iata: dict[str, str],
) -> tuple[str | None, str | None]:
    pref_o, pref_d = _parse_validation_airports(validation_raw)
    origin_icao = _pick_icao_airport(
        _parse_airport_token_list(origin_raw), pref_o, icao_to_iata
    )
    dest_icao = _pick_icao_airport(
        _parse_airport_token_list(dest_raw), pref_d, icao_to_iata
    )
    if not origin_icao or not dest_icao or origin_icao == dest_icao:
        return None, None
    dep_iata = icao_to_iata.get(origin_icao)
    arr_iata = icao_to_iata.get(dest_icao)
    if not dep_iata or not arr_iata or dep_iata == arr_iata:
        return None, None
    return dep_iata, arr_iata


def _normalize_parquet_flights(
    parquet_path: Path,
    icao_to_iata: dict[str, str],
    code_to_airline_name: dict[str, str],
) -> pd.DataFrame:
    import pyarrow.parquet as pq

    cols = [
        "Airline",
        "Track_Origin_DateTime_UTC",
        "Track_Origin_ApplicableAirports",
        "Track_Destination_ApplicableAirports",
        "Route_Validation_Based_on_Callsign",
    ]
    pf = pq.ParquetFile(parquet_path)
    # Compact unique observed slots: (dep, arr, airline, weekday, hhmm)
    unique_slots: set[tuple[str, str, str, str, str]] = set()
    started = time.perf_counter()
    weekday_names = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

    allow = FLIGHT_HISTORY_ICAO_ALLOWLIST
    for rg_idx in range(pf.metadata.num_row_groups):
        df = pf.read_row_group(rg_idx, columns=cols).to_pandas()
        airline = df["Airline"].fillna("").astype(str).str.upper().str.strip()
        keep = airline.isin(allow)
        df = df.loc[keep]
        if df.empty:
            continue

        dts = pd.to_datetime(
            df["Track_Origin_DateTime_UTC"],
            utc=True,
            errors="coerce",
            format="ISO8601",
        )
        valid_dt = dts.notna()
        df = df.loc[valid_dt]
        dts = dts.loc[valid_dt]
        if df.empty:
            continue

        airlines = (
            df["Airline"]
            .fillna("")
            .astype(str)
            .str.upper()
            .str.strip()
            .map(lambda code: code_to_airline_name.get(code, code))
        )

        # Fast path: single airport listed at each end.
        origin_single = (
            df["Track_Origin_ApplicableAirports"]
            .astype(str)
            .str.extract(r"^\['([A-Z0-9]{3,4})'\]$", expand=False)
            .str.upper()
            .map(icao_to_iata)
        )
        dest_single = (
            df["Track_Destination_ApplicableAirports"]
            .astype(str)
            .str.extract(r"^\['([A-Z0-9]{3,4})'\]$", expand=False)
            .str.upper()
            .map(icao_to_iata)
        )
        use_single = (
            origin_single.notna()
            & dest_single.notna()
            & (origin_single != dest_single)
        )
        dep_iata = origin_single.where(use_single)
        arr_iata = dest_single.where(use_single)

        # Fallback: validation route and/or multi-airport candidate lists.
        unresolved = ~use_single
        if unresolved.any():
            sub = df.loc[unresolved]
            resolved_dep: list[str | None] = []
            resolved_arr: list[str | None] = []
            for o_raw, d_raw, v_raw in zip(
                sub["Track_Origin_ApplicableAirports"],
                sub["Track_Destination_ApplicableAirports"],
                sub["Route_Validation_Based_on_Callsign"],
            ):
                dep, arr = _resolve_airports_for_row(
                    o_raw, d_raw, v_raw, icao_to_iata
                )
                resolved_dep.append(dep)
                resolved_arr.append(arr)
            dep_iata.loc[unresolved] = resolved_dep
            arr_iata.loc[unresolved] = resolved_arr

        ok = (
            dep_iata.notna()
            & arr_iata.notna()
            & (dep_iata != arr_iata)
            & airlines.notna()
        )
        if not ok.any():
            continue

        weekdays = dts.dt.dayofweek.map(lambda i: weekday_names[int(i)])
        hhmms = dts.dt.strftime("%H:%M")
        for dep, arr, airline_name, weekday, hhmm in zip(
            dep_iata.loc[ok],
            arr_iata.loc[ok],
            airlines.loc[ok],
            weekdays.loc[ok],
            hhmms.loc[ok],
        ):
            unique_slots.add((dep, arr, airline_name, weekday, hhmm))

        if (rg_idx + 1) % 2 == 0 or rg_idx + 1 == pf.metadata.num_row_groups:
            log_event(
                "PARSE",
                "Flight history parquet "
                f"{rg_idx + 1}/{pf.metadata.num_row_groups} row groups "
                f"({len(unique_slots):,} unique schedule slots, "
                f"{time.perf_counter() - started:.1f}s)",
            )

    if not unique_slots:
        return pd.DataFrame(
            columns=["datetime_utc", "departure_iata", "arrival_iata", "airline"]
        )

    # Materialize one synthetic UTC timestamp per unique weekday/time slot.
    weekday_to_date = {
        "Mon": "2026-07-06",
        "Tue": "2026-07-07",
        "Wed": "2026-07-08",
        "Thu": "2026-07-09",
        "Fri": "2026-07-10",
        "Sat": "2026-07-11",
        "Sun": "2026-07-12",
    }
    rows = [
        {
            "datetime_utc": f"{weekday_to_date[weekday]}T{hhmm}:00+00:00",
            "departure_iata": dep,
            "arrival_iata": arr,
            "airline": airline_name,
        }
        for dep, arr, airline_name, weekday, hhmm in unique_slots
    ]
    return pd.DataFrame(
        rows, columns=["datetime_utc", "departure_iata", "arrival_iata", "airline"]
    )


def load_observed_flights_schedule(
    flights_path: Path,
    airports: pd.DataFrame | None = None,
    code_to_airline_name: dict[str, str] | None = None,
    cache_csv: Path = DEFAULT_FLIGHTS_CACHE_CSV,
    schedule_cache: Path = DEFAULT_FLIGHTS_SCHEDULE_CACHE,
) -> dict[tuple[str, str], dict[str, dict[str, list[str]]]]:
    if not flights_path.exists():
        log_event("WARN", f"Flight history file not found: {flights_path}")
        return {}

    if _cache_is_fresh(schedule_cache, flights_path):
        cached = _load_schedule_pickle(schedule_cache)
        if cached is not None:
            log_event(
                "FILE",
                f"Using cached route schedule ({schedule_cache}) "
                f"with {len(cached):,} route pairs",
            )
            return cached

    suffix = flights_path.suffix.lower()
    if suffix == ".parquet":
        if _cache_is_fresh(cache_csv, flights_path):
            log_event(
                "FILE",
                f"Using cached flight history CSV ({cache_csv}) derived from {flights_path.name}",
            )
            try:
                flights = pd.read_csv(cache_csv)
            except Exception as exc:
                log_event("WARN", f"Failed reading flight cache CSV: {exc}")
                return {}
            route_schedule = _schedule_from_flights_frame(flights)
            _save_schedule_pickle(schedule_cache, route_schedule)
            return route_schedule

        if airports is None or code_to_airline_name is None:
            log_event(
                "WARN",
                "Parquet flight history requires airports + airline reference for ICAO mapping.",
            )
            return {}

        log_event("PARSE", f"Building observed schedules from {flights_path}")
        icao_to_iata = build_icao_to_iata(airports)
        try:
            flights = _normalize_parquet_flights(
                flights_path, icao_to_iata, code_to_airline_name
            )
        except Exception as exc:
            log_event("WARN", f"Failed parsing flight history parquet: {exc}")
            return {}

        if flights.empty:
            log_event("WARN", "No usable flights found in parquet history file.")
            return {}

        try:
            cache_csv.parent.mkdir(parents=True, exist_ok=True)
            flights.to_csv(cache_csv, index=False)
            log_event(
                "FILE",
                f"Cached normalized flight history to {cache_csv} ({len(flights):,} rows)",
            )
        except Exception as exc:
            log_event("WARN", f"Could not write flight history cache CSV: {exc}")

        route_schedule = _schedule_from_flights_frame(flights)
        _save_schedule_pickle(schedule_cache, route_schedule)
        return route_schedule

    # Legacy / cache CSV path.
    try:
        flights = pd.read_csv(flights_path)
    except Exception as exc:
        log_event("WARN", f"Failed reading flights CSV {flights_path}: {exc}")
        return {}
    route_schedule = _schedule_from_flights_frame(flights)
    _save_schedule_pickle(schedule_cache, route_schedule)
    return route_schedule


def build_route_panel(
    selection: dict,
    route_to_airlines: dict[tuple[str, str], set[str]],
    route_schedule: dict[tuple[str, str], dict[str, dict[str, list[str]]]],
    selected_airlines: list[str] | None = None,
) -> list:
    source = selection.get("source")
    dest = selection.get("dest")
    if not source:
        return [
            html.H4("Route details"),
            html.P(
                "Click an origin, then a destination. Times below are observed UTC departures.",
                className="muted",
            ),
        ]
    if not dest:
        return [
            html.H4("Route details"),
            html.P(f"Origin {source}", className="mono"),
            html.P("Now choose a destination on the map.", className="muted"),
        ]

    route_key = (source, dest)
    airlines = sorted(route_to_airlines.get(route_key, set()))
    if selected_airlines:
        sel = set(selected_airlines)
        airlines = [a for a in airlines if a in sel]
    if not airlines:
        filtered_out = bool(selected_airlines and route_to_airlines.get(route_key))
        return [
            html.H4(f"{source} → {dest}"),
            html.P(
                "None of the selected airlines fly this route."
                if filtered_out
                else "No airline data found for this route in the routes dataset.",
                className="muted",
            ),
        ]

    weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    panel_children = [
        html.H4(f"{source} → {dest}", className="mono"),
        html.P("Airlines and observed daily times (UTC).", className="muted"),
    ]

    for airline in airlines:
        panel_children.append(html.H5(airline, style={"marginBottom": "4px"}))
        per_day = route_schedule.get(route_key, {}).get(airline, {})
        if not per_day:
            panel_children.append(
                html.Div(
                    "No observed time data in local flight history.",
                    style={"marginBottom": "10px"},
                )
            )
            continue
        for wd in weekdays:
            times = per_day.get(wd, [])
            text = ", ".join(times[:12]) if times else "-"
            panel_children.append(html.Div(f"{wd}: {text}"))
        panel_children.append(html.Div(style={"height": "8px"}))

    return panel_children


def format_airline_names(names: list[str], max_show: int = 10) -> str:
    if not names:
        return "—"
    if len(names) <= max_show:
        return ", ".join(names)
    head = ", ".join(names[:max_show])
    return f"{head} (+{len(names) - max_show} more)"


def airlines_on_leg_filtered(
    origin: str,
    dest: str,
    route_to_airlines: dict[tuple[str, str], set[str]],
    selected_airlines: list[str],
) -> list[str]:
    names = sorted(route_to_airlines.get((origin, dest), set()))
    if selected_airlines:
        sel = set(selected_airlines)
        names = [n for n in names if n in sel]
    return names


def one_stop_hub_airports(
    origin: str,
    dest: str,
    active_routes_by_source: dict[str, set[str]],
) -> list[str]:
    """Airports X with origin→X and X→dest in the directed route graph (X not origin or dest)."""
    if origin == dest:
        return []
    hubs: list[str] = []
    for x in active_routes_by_source.get(origin, set()):
        if x in (origin, dest):
            continue
        if dest in active_routes_by_source.get(x, set()):
            hubs.append(x)
    return sorted(set(hubs))


def route_combinations_up_to_one_stop(
    origin: str | None,
    dest: str | None,
    active_routes_by_source: dict[str, set[str]],
) -> list[tuple[str, ...]]:
    """All directed paths origin->dest with at most one stop."""
    if not origin or not dest:
        return []
    a = origin.strip().upper()
    b = dest.strip().upper()
    if not a or not b or a == b:
        return []
    paths: list[tuple[str, ...]] = []
    if b in active_routes_by_source.get(a, set()):
        paths.append((a, b))
    for x in one_stop_hub_airports(a, b, active_routes_by_source):
        paths.append((a, x, b))
    return paths


def two_stop_route_paths(
    origin: str,
    dest: str,
    active_routes_by_source: dict[str, set[str]],
    limit: int = 160,
) -> list[tuple[str, ...]]:
    """Directed paths origin→X→Y→dest. Used only when no one-stop path exists."""
    a = origin.strip().upper()
    b = dest.strip().upper()
    if not a or not b or a == b:
        return []
    paths: list[tuple[str, ...]] = []
    for x in active_routes_by_source.get(a, ()):
        if x in (a, b):
            continue
        for y in active_routes_by_source.get(x, ()):
            if y in (a, b, x):
                continue
            if b in active_routes_by_source.get(y, ()):
                paths.append((a, x, y, b))
                if len(paths) >= limit:
                    return paths
    return paths


def route_legs_from_paths(paths: list[tuple[str, ...]]) -> list[tuple[str, str, int]]:
    """Unique legs tagged for drawing. Band 10 is the lightest hop, 11 the middle, 9 the last or a nonstop."""
    seen: set[tuple[str, str]] = set()
    light: list[tuple[str, str, int]] = []
    middle: list[tuple[str, str, int]] = []
    deep: list[tuple[str, str, int]] = []

    def add(src: str, dst: str, band: int, bucket: list[tuple[str, str, int]]) -> None:
        leg = (src, dst)
        if leg in seen:
            return
        seen.add(leg)
        bucket.append((src, dst, band))

    for path in paths:
        if len(path) == 2:
            add(path[0], path[1], 9, deep)
        elif len(path) == 3:
            add(path[0], path[1], 10, light)
            add(path[1], path[2], 9, deep)
        elif len(path) >= 4:
            add(path[0], path[1], 10, light)
            add(path[1], path[2], 11, middle)
            add(path[-2], path[-1], 9, deep)
    return light + middle + deep


def build_route_checker_content(
    from_iata: str | None,
    to_iata: str | None,
    active_routes_by_source: dict[str, set[str]],
    route_to_airlines: dict[tuple[str, str], set[str]],
    selected_airlines: list[str],
    iata_to_caption: dict[str, str],
) -> list:
    if not from_iata or not to_iata:
        return [
            html.P(
                "Pick two airports to see whether a nonstop exists in the "
                "current map network (respects airline filters).",
                className="muted",
                style={"margin": 0, "lineHeight": "1.45"},
            )
        ]
    a, b = from_iata.strip().upper(), to_iata.strip().upper()
    if a == b:
        return [
            html.P(
                "Choose two different airports.",
                className="warn",
                style={"margin": 0},
            )
        ]
    if a not in iata_to_caption or b not in iata_to_caption:
        return [
            html.P(
                "Unknown airport code (not in this app’s commercial set).",
                className="warn",
                style={"margin": 0},
            )
        ]

    direct_edge = b in active_routes_by_source.get(a, set())
    leg_airlines = airlines_on_leg_filtered(a, b, route_to_airlines, selected_airlines)

    if direct_edge:
        if leg_airlines:
            body = f"Nonstop {a} → {b} is in the dataset. Carriers (with current filter): {format_airline_names(leg_airlines)}."
        elif selected_airlines:
            body = (
                f"Nonstop {a} → {b} exists on the map, but none of the selected "
                "airlines operate this leg in the routes data."
            )
        else:
            body = (
                f"Nonstop {a} → {b} is in the dataset. Carriers: "
                f"{format_airline_names(leg_airlines)}."
            )
        return [
            html.P(body, style={"margin": 0, "lineHeight": "1.4"}),
            html.P(
                f"{iata_to_caption[a]} → {iata_to_caption[b]}",
                className="muted",
                style={"margin": "6px 0 0 0", "fontSize": "11px"},
            ),
        ]

    body = f"No nonstop {a} → {b} in the current network (airline filters apply)."
    return [
        html.P(body, style={"margin": 0, "lineHeight": "1.45"}),
        html.P(
            f"{iata_to_caption[a]} → {iata_to_caption[b]}",
            className="muted",
            style={"margin": "6px 0 0 0", "fontSize": "11px"},
        ),
    ]


def build_route_planner_content(
    from_iata: str | None,
    to_iata: str | None,
    active_routes_by_source: dict[str, set[str]],
    route_to_airlines: dict[tuple[str, str], set[str]],
    selected_airlines: list[str],
    iata_to_caption: dict[str, str],
) -> list:
    if not from_iata or not to_iata:
        return [
            html.P(
                "Same airports as above. Lists every itinerary with at most one stop "
                "(two segments), using only legs that appear with your airline filter.",
                className="muted",
                style={"margin": 0, "lineHeight": "1.45"},
            )
        ]
    a, b = from_iata.strip().upper(), to_iata.strip().upper()
    if a == b or a not in iata_to_caption or b not in iata_to_caption:
        return [
            html.P(
                "Set valid, distinct airports to see itineraries.",
                className="muted",
                style={"margin": 0},
            )
        ]

    blocks: list = []
    direct = b in active_routes_by_source.get(a, set())
    if direct:
        air = airlines_on_leg_filtered(a, b, route_to_airlines, selected_airlines)
        blocks.append(
            html.Div(
                className="ticket",
                children=[
                    html.Div(
                        html.Strong("Nonstop"),
                        className="ticket-kicker",
                    ),
                    html.Div(f"{a} → {b}", className="mono"),
                    html.Div(
                        format_airline_names(air) if air else "— (no carriers match filter)"
                        if selected_airlines
                        else format_airline_names(air),
                        className="muted ticket-airlines",
                    ),
                ],
            )
        )

    hubs = one_stop_hub_airports(a, b, active_routes_by_source)
    for x in hubs:
        leg1 = airlines_on_leg_filtered(a, x, route_to_airlines, selected_airlines)
        leg2 = airlines_on_leg_filtered(x, b, route_to_airlines, selected_airlines)
        cap_x = iata_to_caption.get(x, x)
        blocks.append(
            html.Div(
                className="ticket",
                children=[
                    html.Div(
                        html.Strong("1 stop"),
                        className="ticket-kicker",
                    ),
                    html.Div(
                        f"{a} → {x} → {b}",
                        className="mono",
                    ),
                    html.Div(cap_x, className="muted", style={"fontSize": "10px", "margin": "2px 0 6px 0"}),
                    html.Div(
                        [
                            html.Span("Leg 1: ", style={"fontWeight": "600"}),
                            html.Span(
                                format_airline_names(leg1)
                                if leg1
                                else ("—" if not selected_airlines else "no filter match")
                            ),
                        ],
                        style={"fontSize": "11px"},
                    ),
                    html.Div(
                        [
                            html.Span("Leg 2: ", style={"fontWeight": "600"}),
                            html.Span(
                                format_airline_names(leg2)
                                if leg2
                                else ("—" if not selected_airlines else "no filter match")
                            ),
                        ],
                        style={"fontSize": "11px", "marginTop": "2px"},
                    ),
                ],
            )
        )

    if not blocks:
        blocks.append(
            html.P(
                "No nonstop or single-stop connection in the current network.",
                className="muted",
                style={"margin": 0},
            )
        )

    return blocks


def selection_from_route_airport_dropdowns(
    from_val: str | None, to_val: str | None
) -> dict[str, str | None]:
    """Map From/To dropdown values to selection-store shape (uppercase IATA)."""
    fr = (
        from_val.strip().upper()
        if isinstance(from_val, str) and from_val.strip()
        else None
    )
    to = (
        to_val.strip().upper()
        if isinstance(to_val, str) and to_val.strip()
        else None
    )
    if not fr:
        return {"source": None, "dest": None}
    if not to or to == fr:
        return {"source": fr, "dest": None}
    return {"source": fr, "dest": to}


def filter_airports_with_commercial_routes(
    airports: pd.DataFrame, routes: pd.DataFrame
) -> pd.DataFrame:
    valid_iata = set(airports["iata_code"].tolist())
    connected_iata = set(routes["source_iata"].tolist()) | set(routes["dest_iata"].tolist())
    connected_iata = connected_iata.intersection(valid_iata)
    return airports[airports["iata_code"].isin(connected_iata)].copy()


def run_interactive_server(
    airports: pd.DataFrame,
    routes_by_source: dict[str, set[str]],
    route_to_airlines: dict[tuple[str, str], set[str]],
    route_schedule: dict[tuple[str, str], dict[str, dict[str, list[str]]]],
    airline_to_routes_by_source: dict[str, dict[str, set[str]]],
    airline_to_connected_airports: dict[str, set[str]],
    airline_options: list[str],
    host: str,
    port: int,
) -> None:
    airports = prepare_airports_for_map(airports)

    airline_merge_cache: dict[
        tuple[str, ...], tuple[dict[str, set[str]], set[str]]
    ] = {}

    def get_merged_network(sel: list[str]) -> tuple[dict[str, set[str]], set[str] | None]:
        if not sel:
            return routes_by_source, None
        key = tuple(sorted(sel))
        if key not in airline_merge_cache:
            airline_merge_cache[key] = merge_airline_filters(
                list(key),
                airline_to_routes_by_source,
                airline_to_connected_airports,
            )
        return airline_merge_cache[key]

    resolved_myid_airlines = resolve_myid_travel_airlines(airline_options)
    log_event(
        "DATA",
        "MyID travel preset: "
        f"{len(resolved_myid_airlines)} airlines matched in route data "
        f"(from {len(MYID_TRAVEL_AIRLINE_LABELS_RAW)} labels).",
    )
    resolved_asian_myid_airlines = resolve_asian_myid_airlines(airline_options)
    log_event(
        "DATA",
        "Asian MyID preset: "
        f"{len(resolved_asian_myid_airlines)} airlines matched in route data "
        f"(from {len(ASIAN_MYID_AIRLINE_LABELS_RAW)} labels).",
    )

    log_event("DATA", "Building world route line geometry for 'All routes' map mode…")
    _g_lon, _g_lat, _g_total, _g_drawn = build_global_route_network_lines(
        airports, routes_by_source
    )
    global_route_lines_for_ui = (_g_lon, _g_lat)
    global_route_stats_for_ui = (_g_total, _g_drawn)
    log_event(
        "DATA",
        f"'All routes' geometry ready: {_g_drawn:,} segments drawn from {_g_total:,} route legs.",
    )

    ap_route_dd = airports.sort_values(
        ["iso_country", "municipality", "iata_code"], na_position="last"
    )
    iata_to_plain_caption: dict[str, str] = {}
    airport_route_tool_options: list[dict[str, str]] = []
    for _, row in ap_route_dd.iterrows():
        iata = str(row["iata_code"]).upper()
        municipality = row["municipality"]
        country = row["iso_country"]
        mun_s = str(municipality) if pd.notna(municipality) else "?"
        ctry_s = str(country) if pd.notna(country) else "?"
        cap = f"{iata} — {row['name']}, {mun_s} ({ctry_s})"
        iata_to_plain_caption[iata] = cap
        airport_route_tool_options.append({"label": cap, "value": iata})

    mesh_lines_cache: OrderedDict[
        tuple[str, ...],
        tuple[tuple[list[float | None], list[float | None]], tuple[int, int]],
    ] = OrderedDict()
    mesh_cache_max = 32

    def get_mesh_lines(
        sel: list[str], merged_routes: dict[str, set[str]]
    ) -> tuple[
        tuple[list[float | None], list[float | None]], tuple[int, int]
    ]:
        if not sel:
            return global_route_lines_for_ui, global_route_stats_for_ui
        key = tuple(sorted(sel))
        if key in mesh_lines_cache:
            mesh_lines_cache.move_to_end(key)
            return mesh_lines_cache[key]
        m_lon, m_lat, m_tot, m_dr = build_global_route_network_lines(
            airports, merged_routes
        )
        val: tuple[
            tuple[list[float | None], list[float | None]], tuple[int, int]
        ] = ((m_lon, m_lat), (m_tot, m_dr))
        mesh_lines_cache[key] = val
        if len(mesh_lines_cache) > mesh_cache_max:
            mesh_lines_cache.popitem(last=False)
        return val

    airport_lookup = airports.set_index("iata_code")

    dash_app = Dash(__name__)
    dash_app.layout = html.Div(
        className="app-shell",
        children=[
            dcc.Store(id="selection-store", data={"source": None, "dest": None}),
            dcc.Store(id="selected-airlines-store", data=[]),
            dcc.Store(id="route-combos-store", data={"active": False}),
            dcc.Store(id="route-finder-store", data={"active": False}),
            dcc.Store(id="map-look-store", data={"style": "night", "tilt": True}),
            dcc.Store(id="map-payload", data=build_map(airports, routes_by_source)),
            dcc.Store(id="map-mesh"),
            dcc.Store(id="map-mesh-key", data="off"),
            dcc.Store(id="map-click"),
            dcc.Store(id="map-render-sink"),
            html.Div(className="vignette"),
            html.Div(id="two-stop-banner", className="two-stop-banner is-hidden"),
            html.Div(
                id="dock-shell",
                className="dock-shell",
                children=[
            html.Div(
                id="route-info-panel",
                className="dock",
                children=[
                    html.Div(
                        className="brand",
                        children=[
                            html.Div("AIRWAYS", className="brand-mark"),
                            html.Div("Flight atlas", className="brand-sub"),
                        ],
                    ),
                    html.Button(
                        "Route Finder",
                        id="route-finder-toggle",
                        n_clicks=0,
                        className="btn btn-ghost route-finder-btn",
                        title="Pick two cities. The first stays marked and every city remains. The second shows direct and one-stop routes.",
                    ),
                    html.Div("Airlines", className="section-label"),
                    dcc.Dropdown(
                        id="airline-filter",
                        options=[{"label": a, "value": a} for a in airline_options],
                        value=None,
                        clearable=True,
                        searchable=True,
                        placeholder="Add an airline…",
                    ),
                    html.Div(
                        className="toggle-row",
                        children=[
                            dcc.Checklist(
                                id="show-all-routes-toggle",
                                options=[{"label": " All routes", "value": "on"}],
                                value=[],
                            ),
                        ],
                    ),
                    html.Div(id="selected-airlines-chips", className="chip-list"),
                    html.Div(
                        className="btn-row",
                        children=[
                            html.Button(
                                "Iberia MyID",
                                id="myid-travel-preset-button",
                                n_clicks=0,
                                className="btn btn-primary",
                            ),
                            html.Button(
                                "Asian MyID",
                                id="asian-myid-preset-button",
                                n_clicks=0,
                                className="btn btn-teal",
                            ),
                        ],
                    ),
                    html.Button(
                        "Clear airlines",
                        id="clear-airlines-button",
                        n_clicks=0,
                        className="btn btn-ghost",
                    ),
                    html.Div("From / To", className="section-label"),
                    dcc.Dropdown(
                        id="route-tool-from",
                        options=airport_route_tool_options,
                        value=None,
                        clearable=True,
                        searchable=True,
                        placeholder="Origin airport…",
                    ),
                    dcc.Dropdown(
                        id="route-tool-to",
                        options=airport_route_tool_options,
                        value=None,
                        clearable=True,
                        searchable=True,
                        placeholder="Destination airport…",
                        style={"marginTop": "8px"},
                    ),
                    html.Div(id="route-checker-content"),
                    html.P(
                        "Nonstop and one-stop itineraries, using the same airline filter as the map.",
                        className="muted",
                        style={"margin": "0 0 8px 0"},
                    ),
                    html.Button(
                        "Show route combinations on map",
                        id="route-combos-toggle-btn",
                        n_clicks=0,
                        className="btn btn-teal",
                    ),
                    html.Div(id="route-planner-content", className="planner-scroll"),
                    html.Div(id="route-panel-content", className="route-detail"),
                ],
            ),
            html.Button(
                "Hide",
                id="dock-toggle",
                n_clicks=0,
                className="dock-toggle",
                title="Show or hide the control panel",
            ),
                ],
            ),
            html.Div(
                className="look-switch",
                children=[
                    html.Button(
                        "Night",
                        id="look-night",
                        n_clicks=0,
                        className="look-btn is-active",
                    ),
                    html.Button("Day", id="look-day", n_clicks=0, className="look-btn"),
                    html.Button(
                        "Atlas",
                        id="look-sat",
                        n_clicks=0,
                        className="look-btn",
                        title="Satellite imagery",
                    ),
                    html.Button(
                        "Globe",
                        id="tilt-toggle",
                        n_clicks=0,
                        className="look-btn is-active",
                        title="Globe or flat map",
                    ),
                ],
            ),
            html.Button(
                "Clear route",
                id="reset-selection-button",
                n_clicks=0,
                className="btn btn-ghost clear-route-btn",
                title="Remove the selected cities (Esc)",
            ),
            html.Div(
                id="map-hud",
                className="hud",
                children=[
                    html.Div("World network", className="hud-title"),
                    html.Div("Click a hub to unfold its routes", className="hud-sub"),
                ],
            ),
            html.Div(
                className="legend-card",
                children=[
                    html.Div(
                        className="legend-row",
                        children=[html.Span(className="swatch swatch-mega"), "Mega hub"],
                    ),
                    html.Div(
                        className="legend-row",
                        children=[html.Span(className="swatch swatch-large"), "Large"],
                    ),
                    html.Div(
                        className="legend-row",
                        children=[html.Span(className="swatch swatch-med"), "Medium"],
                    ),
                    html.Div(
                        className="legend-row",
                        children=[html.Span(className="swatch swatch-small"), "Small"],
                    ),
                    html.Div(
                        className="legend-row",
                        children=[html.Span(className="swatch swatch-tiny"), "Really small"],
                    ),
                    html.Div(
                        className="legend-row",
                        children=[html.Span(className="swatch swatch-short"), "Short haul"],
                    ),
                    html.Div(
                        className="legend-row",
                        children=[html.Span(className="swatch swatch-mid"), "Medium haul"],
                    ),
                    html.Div(
                        className="legend-row",
                        children=[html.Span(className="swatch swatch-long"), "Long haul"],
                    ),
                    html.Div(
                        className="legend-row",
                        children=[html.Span(className="swatch swatch-ultra"), "Ultra long"],
                    ),
                ],
            ),
            html.Div(
                id="world-map",
                className="map-stage",
            ),
            html.Div(
                className="orbit-dock",
                children=[
                    html.Button(
                        "Orbit",
                        id="orbit-toggle",
                        n_clicks=0,
                        className="look-btn",
                        title="Slowly turn the globe. Runs in the browser.",
                    ),
                    html.Div(
                        id="heading-dial",
                        className="heading-dial",
                        title="Drag around to turn the globe. Drag toward the rim to look toward a pole.",
                        children=[
                            html.Div(className="dial-ring"),
                            html.Div(id="dial-needle", className="dial-needle"),
                        ],
                    ),
                ],
            ),
            html.Button(
                "⌖",
                id="north-compass-button",
                n_clicks=0,
                title="Level the globe, north up",
                className="compass",
            ),
        ],
    )
    dash_app.index_string = """
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>Airways</title>
        {%favicon%}
        {%css%}
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@450;560&family=Outfit:wght@380;520;640&display=swap" rel="stylesheet">
        <link href="https://unpkg.com/maplibre-gl@5.6.1/dist/maplibre-gl.css" rel="stylesheet">
        <script src="https://unpkg.com/maplibre-gl@5.6.1/dist/maplibre-gl.js"></script>
        <style>
            html, body, #react-entry-point { background: #05080f; }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
    </html>
"""

    dash_app.clientside_callback(
        "window.airwaysRenderMap",
        Output("map-render-sink", "data"),
        Input("map-payload", "data"),
        Input("map-mesh", "data"),
    )

    @dash_app.callback(
        Output("airline-filter", "options"),
        Input("selected-airlines-store", "data"),
    )
    def airline_dropdown_options(selected: list | None) -> list[dict[str, str]]:
        chosen = set(selected or [])
        return [{"label": a, "value": a} for a in airline_options if a not in chosen]

    @dash_app.callback(
        Output("selected-airlines-chips", "children"),
        Input("selected-airlines-store", "data"),
    )
    def render_airline_chips(selected: list | None):
        names = list(selected or [])
        if not names:
            return []
        rows = [
            html.Div(
                className="airline-chip",
                children=[
                    html.Span(name),
                    html.Button(
                        "×",
                        id={"type": "remove-airline", "index": i},
                        n_clicks=0,
                        title="Remove",
                        className="chip-x",
                    ),
                ],
            )
            for i, name in enumerate(names)
        ]
        count = len(names)
        label = f"{count} airline" + ("s" if count != 1 else "") + " selected"
        return html.Details(
            className="airline-picker",
            children=[
                html.Summary(
                    className="airline-summary",
                    children=[
                        html.Span(label, className="airline-summary-label"),
                        html.Button(
                            "Clear all",
                            id={"type": "clear-airlines", "index": 0},
                            n_clicks=0,
                            type="button",
                            title="Remove all selected airlines",
                            className="chip-clear",
                        ),
                    ],
                ),
                html.Div(className="airline-menu", children=rows),
            ],
        )

    @dash_app.callback(
        Output("selected-airlines-store", "data"),
        Output("airline-filter", "value"),
        Output("show-all-routes-toggle", "value"),
        Input("airline-filter", "value"),
        Input({"type": "remove-airline", "index": ALL}, "n_clicks"),
        Input("myid-travel-preset-button", "n_clicks"),
        Input("asian-myid-preset-button", "n_clicks"),
        Input("clear-airlines-button", "n_clicks"),
        Input({"type": "clear-airlines", "index": ALL}, "n_clicks"),
        State("selected-airlines-store", "data"),
        prevent_initial_call=True,
    )
    def sync_selected_airlines(
        dropdown_val,
        _remove_clicks,
        _myid_clicks,
        _asian_myid_clicks,
        _clear_clicks,
        _clear_all_clicks,
        current,
    ):
        current = list(current or [])
        tid = ctx.triggered_id
        if tid == "clear-airlines-button" or (
            isinstance(tid, dict) and tid.get("type") == "clear-airlines"
        ):
            # The clear button is recreated whenever the chip list renders, which
            # reports n_clicks as 0. Only an actual click should empty the selection.
            click_count = ctx.triggered[0].get("value") if ctx.triggered else None
            if isinstance(tid, dict) and not click_count:
                return no_update, no_update, no_update
            return [], None, no_update
        if tid == "myid-travel-preset-button":
            return list(resolved_myid_airlines), None, []
        if tid == "asian-myid-preset-button":
            return list(resolved_asian_myid_airlines), None, []
        if tid == "airline-filter":
            if not dropdown_val:
                return no_update, no_update, no_update
            if dropdown_val in current:
                return current, None, no_update
            return current + [dropdown_val], None, no_update
        if isinstance(tid, dict) and tid.get("type") == "remove-airline":
            idx = int(tid["index"])
            nxt = [x for j, x in enumerate(current) if j != idx]
            return nxt, no_update, no_update
        return no_update, no_update, no_update

    @dash_app.callback(
        Output("selection-store", "data"),
        Input("map-click", "data"),
        Input("reset-selection-button", "n_clicks"),
        Input("route-tool-from", "value"),
        Input("route-tool-to", "value"),
        State("selection-store", "data"),
        State("selected-airlines-store", "data"),
        State("route-finder-store", "data"),
        prevent_initial_call=True,
    )
    def update_selection(
        click_data,
        reset_clicks,
        route_from,
        route_to,
        current_selection,
        selected_airlines_state,
        route_finder_state,
    ):
        finder = bool((route_finder_state or {}).get("active"))
        if ctx.triggered_id == "reset-selection-button":
            return {"source": None, "dest": None}

        if ctx.triggered_id in {"route-tool-from", "route-tool-to"}:
            new_sel = selection_from_route_airport_dropdowns(route_from, route_to)
            selected_airlines = list(selected_airlines_state or [])
            active_routes, visible_iata_filter = get_merged_network(selected_airlines)
            src, dst = new_sel.get("source"), new_sel.get("dest")
            if selected_airlines and src and src not in visible_iata_filter:
                new_sel = {"source": None, "dest": None}
            elif (
                src
                and dst
                and not finder
                and dst not in active_routes.get(src, set())
            ):
                new_sel = {"source": src, "dest": None}
            cur = current_selection or {}
            if cur.get("source") == new_sel.get("source") and cur.get("dest") == new_sel.get(
                "dest"
            ):
                return no_update
            return new_sel

        if not isinstance(click_data, dict):
            return current_selection
        clicked = click_data.get("iata")
        if not clicked:
            return current_selection

        source = (current_selection or {}).get("source")
        dest = (current_selection or {}).get("dest")
        clicked = clicked.upper()

        if finder:
            if not source or clicked == source:
                if clicked == source:
                    return {"source": None, "dest": None}
                return {"source": clicked, "dest": None}
            if clicked == dest:
                return {"source": source, "dest": None}
            return {"source": source, "dest": clicked}

        if not source:
            return {"source": clicked, "dest": None}
        if source and not dest:
            if clicked == source:
                return {"source": None, "dest": None}
            return {"source": source, "dest": clicked}
        if clicked == source:
            return {"source": source, "dest": None}
        # source and dest already set: pick another direct destination without changing origin
        active_routes, _vis = get_merged_network(list(selected_airlines_state or []))
        if clicked in active_routes.get(source, set()):
            return {"source": source, "dest": clicked}
        return {"source": clicked, "dest": None}

    @dash_app.callback(
        Output("route-tool-from", "value"),
        Output("route-tool-to", "value"),
        Input("selection-store", "data"),
    )
    def sync_route_tool_dropdowns(selection):
        selection = selection or {}
        return selection.get("source"), selection.get("dest")

    @dash_app.callback(
        Output("route-checker-content", "children"),
        Output("route-planner-content", "children"),
        Input("route-tool-from", "value"),
        Input("route-tool-to", "value"),
        Input("selected-airlines-store", "data"),
    )
    def update_route_checker_and_planner(from_iata, to_iata, selected_airlines_list):
        selected_airlines = list(selected_airlines_list or [])
        active_graph, _vis = get_merged_network(selected_airlines)
        checker = build_route_checker_content(
            from_iata,
            to_iata,
            active_graph,
            route_to_airlines,
            selected_airlines,
            iata_to_plain_caption,
        )
        planner = build_route_planner_content(
            from_iata,
            to_iata,
            active_graph,
            route_to_airlines,
            selected_airlines,
            iata_to_plain_caption,
        )
        return checker, planner

    @dash_app.callback(
        Output("route-combos-store", "data"),
        Output("route-combos-toggle-btn", "children"),
        Input("route-combos-toggle-btn", "n_clicks"),
        Input("route-tool-from", "value"),
        Input("route-tool-to", "value"),
        Input("selected-airlines-store", "data"),
        State("route-combos-store", "data"),
        prevent_initial_call=True,
    )
    def toggle_route_combinations(
        _toggle_clicks, from_iata, to_iata, selected_airlines_list, current_store
    ):
        selected_airlines = list(selected_airlines_list or [])
        active_graph, _vis = get_merged_network(selected_airlines)
        has_combos = bool(
            route_combinations_up_to_one_stop(from_iata, to_iata, active_graph)
        )
        current_active = bool((current_store or {}).get("active", False))
        if ctx.triggered_id == "route-combos-toggle-btn":
            next_active = has_combos and (not current_active)
        else:
            # Keep active state unless current From/To no longer has combinations.
            next_active = current_active and has_combos
        btn_text = (
            "Hide route combinations on map"
            if next_active
            else "Show route combinations on map"
        )
        return {"active": next_active}, btn_text

    @dash_app.callback(
        Output("dock-shell", "className"),
        Output("dock-toggle", "children"),
        Input("dock-toggle", "n_clicks"),
        State("dock-shell", "className"),
        prevent_initial_call=True,
    )
    def toggle_dock(_n_clicks, class_name):
        if class_name and "is-closed" in str(class_name):
            return "dock-shell", "Hide"
        return "dock-shell is-closed", "Panel"

    @dash_app.callback(
        Output("map-look-store", "data"),
        Output("look-night", "className"),
        Output("look-day", "className"),
        Output("look-sat", "className"),
        Output("tilt-toggle", "className"),
        Output("tilt-toggle", "children"),
        Input("look-night", "n_clicks"),
        Input("look-day", "n_clicks"),
        Input("look-sat", "n_clicks"),
        Input("tilt-toggle", "n_clicks"),
        State("map-look-store", "data"),
        prevent_initial_call=True,
    )
    def set_map_look(_night, _day, _sat, _tilt, data):
        look = dict(data or {"style": "night", "tilt": True})
        tid = ctx.triggered_id
        if tid == "look-night":
            look["style"] = "night"
        elif tid == "look-day":
            look["style"] = "day"
        elif tid == "look-sat":
            look["style"] = "sat"
        elif tid == "tilt-toggle":
            look["tilt"] = not bool(look.get("tilt", True))
        style = look.get("style", "night")
        tilt = bool(look.get("tilt", True))

        def btn(active: bool) -> str:
            return "look-btn is-active" if active else "look-btn"

        return (
            look,
            btn(style == "night"),
            btn(style == "day"),
            btn(style == "sat"),
            btn(tilt),
            "Globe" if tilt else "Flat",
        )

    @dash_app.callback(
        Output("route-finder-store", "data"),
        Output("route-finder-toggle", "className"),
        Input("route-finder-toggle", "n_clicks"),
        State("route-finder-store", "data"),
        prevent_initial_call=True,
    )
    def toggle_route_finder(_n_clicks, data):
        active = not bool((data or {}).get("active"))
        class_name = (
            "btn btn-ghost route-finder-btn is-on"
            if active
            else "btn btn-ghost route-finder-btn"
        )
        return {"active": active}, class_name

    @dash_app.callback(
        Output("map-payload", "data"),
        Output("route-panel-content", "children"),
        Output("map-hud", "children"),
        Output("two-stop-banner", "children"),
        Output("two-stop-banner", "className"),
        Output("map-mesh", "data"),
        Output("map-mesh-key", "data"),
        Input("selection-store", "data"),
        Input("selected-airlines-store", "data"),
        Input("show-all-routes-toggle", "value"),
        Input("route-combos-store", "data"),
        Input("route-tool-from", "value"),
        Input("route-tool-to", "value"),
        Input("map-look-store", "data"),
        Input("route-finder-store", "data"),
        State("map-mesh-key", "data"),
    )
    def update_view(
        selection,
        selected_airlines_list,
        show_all_routes_value,
        route_combos_store,
        route_from,
        route_to,
        map_look,
        route_finder_state,
        stored_mesh_key,
    ):
        selection = selection or {"source": None, "dest": None}
        selected_airlines = list(selected_airlines_list or [])
        finder = bool((route_finder_state or {}).get("active"))
        srv = show_all_routes_value if isinstance(show_all_routes_value, list) else []
        show_all_routes = bool(srv) and ("on" in srv)

        active_routes_by_source, visible_iata_filter = get_merged_network(
            selected_airlines
        )

        source = selection.get("source")
        dest = selection.get("dest")
        effective_selection = {"source": source, "dest": dest}
        if show_all_routes:
            panel_airlines = None
        elif selected_airlines:
            panel_airlines = selected_airlines
        else:
            panel_airlines = None

        mesh_lonlat = None
        mesh_stats = None
        finder_paths: list[tuple[str, ...]] = []
        if finder and source and dest:
            finder_paths = route_combinations_up_to_one_stop(
                source, dest, active_routes_by_source
            )
            if not any(len(path) == 3 for path in finder_paths):
                finder_paths = finder_paths + two_stop_route_paths(
                    source, dest, active_routes_by_source
                )
        # Keep the world mesh while Route Finder is waiting for a second city.
        if show_all_routes and (not source or (finder and source and not dest)):
            mesh_lonlat, mesh_stats = get_mesh_lines(
                selected_airlines, active_routes_by_source
            )
        highlighted_combo_legs: list[tuple[str, str, int]] | None = None
        shown_paths: list[tuple[str, ...]] = []
        if finder_paths:
            shown_paths = finder_paths
            highlighted_combo_legs = route_legs_from_paths(finder_paths)
        elif bool((route_combos_store or {}).get("active", False)):
            shown_paths = route_combinations_up_to_one_stop(
                route_from, route_to, active_routes_by_source
            )
            if shown_paths:
                highlighted_combo_legs = route_legs_from_paths(shown_paths)
        combo_only_mode = bool(highlighted_combo_legs)

        def coords_for(codes: list[str]) -> tuple[list[float], list[float]]:
            lons: list[float] = []
            lats: list[float] = []
            for code in codes:
                if code not in airport_lookup.index:
                    continue
                row = airport_lookup.loc[code]
                if isinstance(row, pd.DataFrame):
                    row = row.iloc[0]
                lons.append(float(row["longitude_deg"]))
                lats.append(float(row["latitude_deg"]))
            return lons, lats

        focus = None
        hold_camera = bool(finder and source and not dest)
        if hold_camera:
            pass
        elif source and not dest and source in airport_lookup.index:
            hub_row = airport_lookup.loc[source]
            if isinstance(hub_row, pd.DataFrame):
                hub_row = hub_row.iloc[0]
            hub_lon = float(hub_row["longitude_deg"])
            hub_lat = float(hub_row["latitude_deg"])
            distances: list[float] = []
            for code in active_routes_by_source.get(source, ()):
                if code not in airport_lookup.index:
                    continue
                drow = airport_lookup.loc[code]
                if isinstance(drow, pd.DataFrame):
                    drow = drow.iloc[0]
                distances.append(
                    haversine_km(
                        hub_lat,
                        hub_lon,
                        float(drow["latitude_deg"]),
                        float(drow["longitude_deg"]),
                    )
                )
            distances.sort()
            typical = (
                distances[int((len(distances) - 1) * 0.42)] if distances else 900.0
            )
            zoom = max(2.65, min(5.4, 6.6 - math.log2(max(typical, 80.0) / 150.0)))
            # Slide west so the hub sits in the open map, clear of the left panel.
            focus = (hub_lon - 14.0 / zoom, hub_lat, zoom)
        elif source and dest:
            framed = [source, dest]
            if finder:
                framed.extend(code for path in finder_paths for code in path[1:-1])
            focus = camera_for_points(*coords_for(framed))
        elif visible_iata_filter is not None and 0 < len(visible_iata_filter) <= 280:
            focus = camera_for_points(*coords_for(list(visible_iata_filter)))

        look = dict(map_look or {"style": "night", "tilt": True})
        map_style = str(look.get("style") or "night")
        if map_style not in MAP_STYLE_TOKENS:
            map_style = "night"
        map_tilt = bool(look.get("tilt", True))
        view_token = (
            f"{source or '-'}|{dest or '-'}|{map_style}|{int(map_tilt)}|"
            f"{int(show_all_routes)}|{int(finder)}|"
            + "|".join(selected_airlines)
        )

        def map_pin(code: str, role: str) -> dict | None:
            if code not in airport_lookup.index:
                return None
            row = airport_lookup.loc[code]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            city = row["municipality"] if "municipality" in row.index else None
            missing_city = city is None or (not isinstance(city, str) and bool(pd.isna(city)))
            name = code if missing_city else (str(city).strip() or code)
            return {
                "lon": round(float(row["longitude_deg"]), 4),
                "lat": round(float(row["latitude_deg"]), 4),
                "role": role,
                "name": name,
                "iata": code,
            }

        pins: list[dict] = []
        show_rings = bool(finder or (shown_paths and source and dest))

        def add_pin(code: str | None, role: str, ring: bool) -> None:
            if not code:
                return
            pin = map_pin(code, role)
            if not pin:
                return
            pin["ring"] = ring
            pins.append(pin)

        add_pin(source, "origin", show_rings)
        add_pin(dest, "dest", show_rings)
        seen_layovers: set[str] = set()
        for path in shown_paths:
            for code in path[1:-1]:
                if code in seen_layovers:
                    continue
                seen_layovers.add(code)
                add_pin(code, "layover", True)

        payload = build_map(
            airports,
            active_routes_by_source,
            selected_iata=source,
            selected_destination_iata=dest,
            visible_iata_filter=visible_iata_filter,
            show_all_routes_mode=show_all_routes,
            global_route_lines_lonlat=mesh_lonlat,
            global_route_stats=mesh_stats,
            highlighted_route_legs=highlighted_combo_legs,
            show_selected_hub_routes=not finder and not combo_only_mode,
            show_selected_destination_highlight=not finder and not combo_only_mode,
            keep_all_airports=finder,
            pins=pins,
            hold_camera=hold_camera,
            route_to_airlines=route_to_airlines,
            selected_airlines=selected_airlines,
            layover_paths=shown_paths,
            map_style=map_style,
            map_tilt=map_tilt,
            view_token=view_token,
            focus=focus,
        )
        direct_in_finder = bool(
            finder and source and dest and dest in active_routes_by_source.get(source, set())
        )
        one_stop_count = sum(1 for path in finder_paths if len(path) == 3)
        two_stop_count = sum(1 for path in finder_paths if len(path) >= 4)
        if finder and source and not dest:
            panel = [
                html.H4("Route Finder"),
                html.P(f"Origin {source}", className="mono"),
                html.P(
                    "Every city stays on the map. Choose a second city to draw direct and one-stop routes.",
                    className="muted",
                ),
            ]
        elif finder and source and dest and not direct_in_finder:
            panel = [
                html.H4(f"{source} → {dest}", className="mono"),
                html.P(
                    (
                        "No nonstop or one-stop route. "
                        + (
                            "1 two-stop itinerary is drawn."
                            if two_stop_count == 1
                            else f"{two_stop_count} two-stop itineraries are drawn."
                        )
                    )
                    if one_stop_count == 0 and two_stop_count
                    else (
                        "No nonstop or one-stop route in the current airline filter."
                        if one_stop_count == 0
                        else (
                            "No nonstop in the current airline filter. 1 one-stop itinerary is drawn on the map."
                            if one_stop_count == 1
                            else f"No nonstop in the current airline filter. {one_stop_count} one-stop itineraries are drawn on the map."
                        )
                    ),
                    className="muted",
                ),
            ]
        else:
            panel = build_route_panel(
                effective_selection,
                route_to_airlines,
                route_schedule,
                selected_airlines=panel_airlines,
            )
        if finder and source and dest:
            if direct_in_finder and one_stop_count:
                hud_sub = f"Direct · {one_stop_count} one-stop"
            elif direct_in_finder and two_stop_count:
                hud_sub = f"Direct · {two_stop_count} two-stop"
            elif direct_in_finder:
                hud_sub = "Direct only"
            elif one_stop_count:
                hud_sub = f"No direct · {one_stop_count} one-stop"
            elif two_stop_count:
                hud_sub = f"No direct · {two_stop_count} two-stop"
            else:
                hud_sub = "No direct or one-stop route"
            if selected_airlines:
                hud_sub += " · selected airlines"
            hud_title = f"{source}  →  {dest}"
        elif finder and source:
            hud_title, hud_sub = source, "Route Finder · pick a second city"
        elif source and dest:
            hud_title, hud_sub = f"{source}  →  {dest}", "Pinned route"
        elif source:
            n_out = len(active_routes_by_source.get(source, ()))
            hud_title, hud_sub = source, f"{n_out:,} outgoing routes"
        elif show_all_routes:
            total_e, drawn_e = mesh_stats or (0, 0)
            if drawn_e and total_e and drawn_e < total_e:
                hud_sub = f"{drawn_e:,} of {total_e:,} legs"
            else:
                hud_sub = f"{drawn_e:,} legs" if drawn_e else "Route mesh"
            hud_title = "Full network"
        else:
            n_show = (
                len(visible_iata_filter)
                if visible_iata_filter is not None
                else len(airports)
            )
            hud_title, hud_sub = "World network", f"{n_show:,} commercial airports"
        hud = [
            html.Div(hud_title, className="hud-title"),
            html.Div(hud_sub, className="hud-sub"),
        ]
        if finder and two_stop_count and not one_stop_count:
            banner_text = (
                "Only two-stop routes found, three-leg."
                if not direct_in_finder
                else "No one-stop routes. Two-stop routes found, three-leg."
            )
            banner_class = "two-stop-banner"
        else:
            banner_text = ""
            banner_class = "two-stop-banner is-hidden"
        mesh_key = payload.pop("meshKey", "off")
        mesh_lines = payload.pop("mesh", None)
        if mesh_key == (stored_mesh_key or "off"):
            mesh_out, key_out = no_update, no_update
        else:
            mesh_out, key_out = mesh_lines, mesh_key
        return payload, panel, hud, banner_text, banner_class, mesh_out, key_out

    log_event("UI", f"Starting Dash server at http://{host}:{port}")
    dash_app.run(host=host, port=port, debug=False)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Interactive flight map: click airport to show outgoing routes."
    )
    parser.add_argument(
        "--mode",
        choices=["interactive", "static"],
        default="interactive",
        help="interactive: click airports for routes, static: export plain airport map.",
    )
    parser.add_argument(
        "--save-html",
        type=Path,
        default=None,
        help="Optional output HTML path (mostly useful with --mode static).",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open the interactive window/browser.",
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
        help="Max allowed time for key stages (download/parse/write).",
    )
    parser.add_argument(
        "--airports-csv",
        type=Path,
        default=Path("airports.csv"),
        help="Local CSV path where downloaded airport data is saved.",
    )
    parser.add_argument(
        "--routes-csv",
        type=Path,
        default=Path("routes.csv"),
        help="Local CSV path where downloaded route data is saved.",
    )
    parser.add_argument(
        "--airlines-csv",
        type=Path,
        default=Path("airlines.csv"),
        help="Local CSV path where downloaded airlines reference is saved.",
    )
    parser.add_argument(
        "--flights-data",
        type=Path,
        default=DEFAULT_FLIGHTS_PARQUET
        if DEFAULT_FLIGHTS_PARQUET.exists()
        else DEFAULT_FLIGHTS_PARQUET_FULL,
        help=(
            "Local flight history file for the route time panel "
            "(.parquet ADS-B schedules or normalized .csv). "
            "Defaults to airline-filtered parquet when present."
        ),
    )
    parser.add_argument(
        "--flights-cache-csv",
        type=Path,
        default=DEFAULT_FLIGHTS_CACHE_CSV,
        help="Normalized CSV cache written from parquet flight history.",
    )
    parser.add_argument(
        "--flights-schedule-cache",
        type=Path,
        default=DEFAULT_FLIGHTS_SCHEDULE_CACHE,
        help="Pickle cache of aggregated route schedules for fast startup.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Dash host.")
    parser.add_argument("--port", type=int, default=8050, help="Dash port.")
    args = parser.parse_args()

    log_event("START", "Loading airport and route data")
    airports = load_commercial_airports(
        DATA_URL,
        local_csv_path=args.airports_csv,
        request_timeout_seconds=args.request_timeout_seconds,
        stage_timeout_seconds=args.stage_timeout_seconds,
    )
    log_event("DATA", f"Commercial airports loaded: {len(airports):,}")

    routes = load_routes(
        ROUTES_URL,
        local_csv_path=args.routes_csv,
        request_timeout_seconds=args.request_timeout_seconds,
        stage_timeout_seconds=args.stage_timeout_seconds,
    )
    code_to_airline_name = load_airlines_reference(
        AIRLINES_URL,
        local_csv_path=args.airlines_csv,
        request_timeout_seconds=args.request_timeout_seconds,
        stage_timeout_seconds=args.stage_timeout_seconds,
    )
    airports = filter_airports_with_commercial_routes(airports, routes)
    log_event(
        "DATA",
        f"Airports with at least one commercial route: {len(airports):,}",
    )
    routes_by_source = build_routes_lookup(airports, routes)
    airports = attach_hub_tiers(airports, routes_by_source)
    route_to_airlines = build_route_airlines_lookup(
        airports, routes, code_to_airline_name
    )
    (
        airline_to_routes_by_source,
        airline_to_connected_airports,
        airline_options,
    ) = build_airline_route_indexes(airports, routes, code_to_airline_name)
    route_schedule = load_observed_flights_schedule(
        args.flights_data,
        airports=airports,
        code_to_airline_name=code_to_airline_name,
        cache_csv=args.flights_cache_csv,
        schedule_cache=args.flights_schedule_cache,
    )
    log_event("DATA", f"Route pairs loaded: {len(routes):,}")
    log_event("DATA", f"Airports with outgoing routes: {len(routes_by_source):,}")
    log_event("DATA", f"Routes with airline labels: {len(route_to_airlines):,}")
    log_event("DATA", f"Airline filters available: {len(airline_options):,}")
    log_event("DATA", f"Observed route schedules loaded: {len(route_schedule):,}")

    build_started = time.perf_counter()
    build_map(prepare_airports_for_map(airports), routes_by_source)
    build_elapsed = assert_duration("Map build", build_started, args.stage_timeout_seconds)
    log_event("MAP", f"Base map payload built in {build_elapsed:.2f}s")

    if args.save_html or args.mode == "static":
        log_event(
            "MAP",
            "The published site is docs/. Refresh its data with: python export_site_data.py",
        )
        if args.mode == "static":
            return

    run_interactive_server(
        airports=airports,
        routes_by_source=routes_by_source,
        route_to_airlines=route_to_airlines,
        route_schedule=route_schedule,
        airline_to_routes_by_source=airline_to_routes_by_source,
        airline_to_connected_airports=airline_to_connected_airports,
        airline_options=airline_options,
        host=args.host,
        port=args.port,
    )


if __name__ == "__main__":
    main()
