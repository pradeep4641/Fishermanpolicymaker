"""
obis.py — OBIS species & occurrence data
Synchronous requests calls to https://api.obis.org/v3
"""

import time
import requests
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Region definitions — OBIS uses WKT geometry or areaid
# Using bounding-box WKT polygons for India's key coastal/marine regions
# ---------------------------------------------------------------------------
REGIONS = {
    "bay_of_bengal": {
        "geometry": "POLYGON((80 5,95 5,95 22,80 22,80 5))",
        "center": (13.0, 87.5),
        "label": "Bay of Bengal",
    },
    "arabian_sea": {
        "geometry": "POLYGON((55 5,77 5,77 25,55 25,55 5))",
        "center": (15.0, 66.0),
        "label": "Arabian Sea",
    },
    "andaman_sea": {
        "geometry": "POLYGON((92 6,100 6,100 16,92 16,92 6))",
        "center": (11.0, 96.0),
        "label": "Andaman Sea",
    },
    "lakshadweep_sea": {
        "geometry": "POLYGON((71 8,75 8,75 14,71 14,71 8))",
        "center": (11.0, 73.0),
        "label": "Lakshadweep Sea",
    },
}

OBIS_BASE = "https://api.obis.org/v3"

# ---------------------------------------------------------------------------
# Simple in-memory cache — (cache_key -> {"data": ..., "expires": timestamp})
# 10-minute TTL to keep demo snappy without hammering OBIS
# ---------------------------------------------------------------------------
_cache: dict = {}
CACHE_TTL = 600  # seconds


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and entry["expires"] > time.time():
        return entry["data"]
    return None


def _cache_set(key: str, data):
    _cache[key] = {"data": data, "expires": time.time() + CACHE_TTL}


def _geometry(region: str) -> str:
    """Return WKT geometry for a region key, falling back to Bay of Bengal."""
    return REGIONS.get(region, REGIONS["bay_of_bengal"])["geometry"]


def _safe_get(url: str, params: dict, timeout: int = 60) -> dict:
    """GET with timeout + basic error handling. OBIS can be slow on big geometry queries."""
    try:
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        return {"error": str(exc), "results": []}


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def get_species(region: str, q: str | None = None) -> list[dict]:
    """
    Return a list of species for the region.
    Uses /v3/checklist (which accepts geometry) to get per-species summary
    including IUCN category and taxon metadata.
    Each item: {scientificName, vernacularName, iucnCategory, taxonID, kingdom, phylum, class}
    """
    cache_key = f"species:{region}:{q}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # /v3/checklist returns one row per taxon with occurrence stats + taxonomy.
    # Fetch a large page and filter client-side to Species rank.
    params = {
        "geometry": _geometry(region),
        "size": 500,
    }
    if q:
        params["scientificname"] = q

    data = _safe_get(f"{OBIS_BASE}/checklist", params)

    results = []
    for rec in data.get("results", []):
        # Only keep true species-level entries
        rank = rec.get("taxonRank") or rec.get("rank") or ""
        if q or rank.lower() == "species":
            results.append({
                "scientificName": rec.get("scientificName", ""),
                "vernacularName": "",
                "iucnCategory":   rec.get("category", "Unknown") or "Unknown",
                "taxonID":        str(rec.get("taxonID", "")),
                "kingdom":        rec.get("kingdom", ""),
                "phylum":         rec.get("phylum", ""),
                "class":          rec.get("class_", "") or rec.get("class", ""),
                "records":        rec.get("records", 0),
            })

    # Sort by record count descending (most-observed first), cap at 100
    results.sort(key=lambda r: r.get("records", 0), reverse=True)
    results = results[:100]

    _cache_set(cache_key, results)
    return results


def get_sightings(region: str, species: str | None = None) -> list[dict]:
    """
    Return occurrence points for map rendering.
    Each item: {lat, lon, date, scientificName, id}
    """
    cache_key = f"sightings:{region}:{species}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    params = {
        "geometry": _geometry(region),
        "size": 200,
        "fields": "decimalLatitude,decimalLongitude,eventDate,scientificName,occurrenceID",
    }
    if species:
        params["scientificname"] = species

    data = _safe_get(f"{OBIS_BASE}/occurrence", params)

    results = []
    for rec in data.get("results", []):
        lat = rec.get("decimalLatitude")
        lon = rec.get("decimalLongitude")
        if lat is None or lon is None:
            continue
        results.append({
            "lat": float(lat),
            "lon": float(lon),
            "date": rec.get("eventDate", ""),
            "scientificName": rec.get("scientificName", "Unknown"),
            "id": rec.get("occurrenceID", ""),
        })

    _cache_set(cache_key, results)
    return results


def get_occurrences_for_period(
    region: str, start_date: str, end_date: str
) -> list[dict]:
    """
    Return raw occurrence records for a date range.
    Each item: {scientificName, lat, lon, date, sst, depth, year}
    Used by calculations.py for health index, comparison, anomaly detection.
    """
    cache_key = f"occurrences:{region}:{start_date}:{end_date}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    params = {
        "geometry": _geometry(region),
        "startdate": start_date,
        "enddate": end_date,
        "size": 500,
        "fields": (
            "decimalLatitude,decimalLongitude,eventDate,scientificName,"
            "sst,depth,occurrenceID,aphiaID"
        ),
    }

    data = _safe_get(f"{OBIS_BASE}/occurrence", params)

    results = []
    for rec in data.get("results", []):
        date_str = rec.get("eventDate", "")
        year = None
        if date_str:
            try:
                year = int(date_str[:4])
            except (ValueError, TypeError):
                pass

        sst_raw = rec.get("sst")
        try:
            sst = float(sst_raw) if sst_raw is not None else None
        except (ValueError, TypeError):
            sst = None

        results.append({
            "scientificName": rec.get("scientificName", "Unknown"),
            "lat": rec.get("decimalLatitude"),
            "lon": rec.get("decimalLongitude"),
            "date": date_str,
            "year": year,
            "sst": sst,
            "depth": rec.get("depth"),
            "id": rec.get("occurrenceID", ""),
        })

    _cache_set(cache_key, results)
    return results


def get_region_labels() -> dict[str, str]:
    """Return {region_key: human_label} for all defined regions."""
    return {k: v["label"] for k, v in REGIONS.items()}
