"""
environment.py — Marine environmental data via Open-Meteo Marine API
No API key required. Returns SST, wave height, swell data.

NOTE: INCOIS (Indian National Centre for Ocean Information Services) does not
expose a usable public REST API — treated as a planned-future source.
NOAA ERDDAP is also noted as a future upgrade for higher-resolution Indian
Ocean data; Open-Meteo is used here for keyless, reliable demo operation.

Open-Meteo marine endpoint uses hourly granularity; we aggregate to daily means.
"""

import requests
from datetime import date
from collections import defaultdict

# Region centroids for Open-Meteo's lat/lon-based queries
REGION_COORDS = {
    "bay_of_bengal":    {"lat": 13.0, "lon": 87.5},
    "arabian_sea":      {"lat": 15.0, "lon": 66.0},
    "andaman_sea":      {"lat": 11.0, "lon": 96.0},
    "lakshadweep_sea":  {"lat": 11.0, "lon": 73.0},
}

MARINE_API   = "https://marine-api.open-meteo.com/v1/marine"
WEATHER_API  = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_API  = "https://archive-api.open-meteo.com/v1/archive"  # historical SST

# Hourly marine variables (wave/swell only — SST comes from weather/archive API)
MARINE_VARS = "wave_height,wave_period,swell_wave_height,ocean_current_velocity"
WEATHER_VARS = "sea_surface_temperature"


def _safe_get(url: str, params: dict, timeout: int = 30) -> dict:
    try:
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        return {"error": str(exc)}


def _hourly_to_daily(times: list[str], values: list) -> dict[str, list]:
    """
    Aggregate hourly readings to daily averages.
    Returns {date_str: [list_of_hourly_values]}, then averaged.
    """
    by_date: dict[str, list] = defaultdict(list)
    for t, v in zip(times, values):
        if v is not None:
            day = t[:10]   # "YYYY-MM-DD"
            by_date[day].append(v)
    return {
        d: round(sum(vs) / len(vs), 3)
        for d, vs in by_date.items()
        if vs
    }


def get_environmental_data(
    region: str, start_date: str, end_date: str
) -> list[dict]:
    """
    Returns [{date, sst, wave_height, wave_period, swell_wave_height,
               ocean_current_velocity}]
    for the region's centroid over the specified date range.

    Dates: ISO 8601 "YYYY-MM-DD". Hourly data aggregated to daily means.
    """
    coords = REGION_COORDS.get(region, REGION_COORDS["bay_of_bengal"])
    lat, lon = coords["lat"], coords["lon"]

    # --- Marine: wave/swell (hourly) ---
    marine_resp = _safe_get(MARINE_API, {
        "latitude":   lat,
        "longitude":  lon,
        "start_date": start_date,
        "end_date":   end_date,
        "hourly":     MARINE_VARS,
    })

    # --- SST: archive API for past data, forecast API for upcoming dates ---
    today_str = date.today().isoformat()

    # Determine split: past portion goes to archive, future to forecast
    past_end   = min(end_date, today_str)
    future_start = today_str  # forecast starts from today

    daily_sst: dict[str, float] = {}

    if start_date <= past_end:
        sst_resp = _safe_get(ARCHIVE_API, {
            "latitude":   lat,
            "longitude":  lon,
            "start_date": start_date,
            "end_date":   past_end,
            "hourly":     WEATHER_VARS,
        })
        h = sst_resp.get("hourly", {})
        daily_sst.update(_hourly_to_daily(h.get("time", []), h.get("sea_surface_temperature", [])))

    if end_date > today_str:
        sst_fcast = _safe_get(WEATHER_API, {
            "latitude":   lat,
            "longitude":  lon,
            "start_date": future_start,
            "end_date":   end_date,
            "hourly":     WEATHER_VARS,
        })
        h = sst_fcast.get("hourly", {})
        daily_sst.update(_hourly_to_daily(h.get("time", []), h.get("sea_surface_temperature", [])))

    marine_h = marine_resp.get("hourly", {})
    m_times  = marine_h.get("time", [])

    # Aggregate marine variables to daily averages
    daily_wave    = _hourly_to_daily(m_times, marine_h.get("wave_height", []))
    daily_period  = _hourly_to_daily(m_times, marine_h.get("wave_period", []))
    daily_swell   = _hourly_to_daily(m_times, marine_h.get("swell_wave_height", []))
    daily_current = _hourly_to_daily(m_times, marine_h.get("ocean_current_velocity", []))
    # daily_sst is already built above from archive/forecast APIs

    # Union of all dates
    all_dates = sorted(
        set(list(daily_wave.keys()) + list(daily_sst.keys()))
    )

    results: list[dict] = []
    for d in all_dates:
        results.append({
            "date":                    d,
            "sst":                     daily_sst.get(d),
            "wave_height":             daily_wave.get(d),
            "wave_period":             daily_period.get(d),
            "swell_wave_height":       daily_swell.get(d),
            "ocean_current_velocity":  daily_current.get(d),
        })

    return results
