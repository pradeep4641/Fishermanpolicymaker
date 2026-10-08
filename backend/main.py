"""
main.py — FastAPI application
All routes, CORS, static file serving, in-memory CSV handling.
"""

import csv
import io
import json
import sys
import os
from datetime import date, timedelta
from typing import Optional

from fastapi import FastAPI, Query, UploadFile, File, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    JSONResponse,
    StreamingResponse,
    HTMLResponse,
    FileResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Adjust path so backend modules import correctly when run from project root
sys.path.insert(0, os.path.dirname(__file__))

# Auto-load .env file if present
_env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(_env_path):
    try:
        with open(_env_path, "r", encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    _k = _k.strip()
                    _v = _v.strip().strip('"').strip("'")
                    if _k and _v and not os.environ.get(_k):
                        os.environ[_k] = _v
    except Exception:
        pass

from obis import get_species, get_sightings, get_occurrences_for_period, get_region_labels, REGIONS
from environment import get_environmental_data
from calculations import (
    regional_health_index,
    compare_periods,
    compare_regions,
    detect_anomalies,
    project_scenario,
    timeseries,
)
from assistant import ask as assistant_ask, translate_text
from report import generate_report

# ---------------------------------------------------------------------------
# Expected columns for uploaded CSVs (documented template)
# ---------------------------------------------------------------------------
EXPECTED_CSV_COLUMNS = {
    "scientificName",
    "decimalLatitude",
    "decimalLongitude",
    "eventDate",
    "region",
}

OPTIONAL_CSV_COLUMNS = {"sst", "depth", "occurrenceID", "vernacularName"}

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Oceanix API",
    description="Marine biodiversity platform for India's coastal waters",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Helper: default date range
# ---------------------------------------------------------------------------
def _default_range(years_back: int = 3) -> tuple[str, str]:
    today = date.today()
    return (today - timedelta(days=365 * years_back)).isoformat(), today.isoformat()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health_check():
    return {"status": "ok", "regions": list(REGIONS.keys())}


@app.get("/api/species")
def species_endpoint(
    region: str = Query("bay_of_bengal"),
    q: Optional[str] = Query(None),
):
    results = get_species(region, q)
    return {"region": region, "count": len(results), "results": results}


@app.get("/api/sightings")
def sightings_endpoint(
    region: str = Query("bay_of_bengal"),
    species: Optional[str] = Query(None),
):
    results = get_sightings(region, species)
    return {"region": region, "count": len(results), "results": results}


@app.get("/api/health-index")
def health_index_endpoint(
    region: str = Query("bay_of_bengal"),
):
    recent_start, recent_end = _default_range(3)
    older_start, older_end   = _default_range(6)[0], _default_range(3)[0]

    recent  = get_occurrences_for_period(region, recent_start, recent_end)
    older   = get_occurrences_for_period(region, older_start,  older_end)
    result  = regional_health_index(recent, older)

    # Also fetch environmental data for the same window and append SST summary
    try:
        env = get_environmental_data(region, recent_start, recent_end)
        sst_vals = [r["sst"] for r in env if r.get("sst") is not None]
        if sst_vals:
            result["env_avg_sst"]   = round(sum(sst_vals) / len(sst_vals), 2)
            result["env_sst_count"] = len(sst_vals)
    except Exception:
        pass

    return {"region": region, **result}


@app.get("/api/compare")
def compare_endpoint(
    region_a: str = Query("bay_of_bengal"),
    region_b: Optional[str] = Query(None),
    period_a: Optional[str] = Query(None),  # "YYYY-MM-DD:YYYY-MM-DD"
    period_b: Optional[str] = Query(None),
):
    def parse(p: str | None, default_years_back: int):
        if not p:
            s, e = _default_range(default_years_back)
            return s, e
        parts = p.split(":")
        return parts[0], parts[1] if len(parts) == 2 else _default_range(default_years_back)

    a_start, a_end = parse(period_a, 6)
    b_start, b_end = parse(period_b, 3)

    records_a = get_occurrences_for_period(region_a, a_start, a_end)

    if region_b and region_b != region_a:
        # Region comparison
        records_b = get_occurrences_for_period(region_b, a_start, a_end)
        result = compare_regions(records_a, records_b)
        result["mode"] = "region"
        result["label_a"] = get_region_labels().get(region_a, region_a)
        result["label_b"] = get_region_labels().get(region_b, region_b)
    else:
        # Period comparison for same region
        records_b = get_occurrences_for_period(region_a, b_start, b_end)
        result = compare_periods(records_a, records_b)
        result["mode"] = "period"
        result["label_a"] = f"{a_start} → {a_end}"
        result["label_b"] = f"{b_start} → {b_end}"

    return {"region_a": region_a, "region_b": region_b, **result}


@app.get("/api/timeseries")
def timeseries_endpoint(
    region: str = Query("bay_of_bengal"),
    metric: str = Query("species_count"),  # species_count | occurrence_count | avg_sst
):
    start, end = _default_range(10)
    records = get_occurrences_for_period(region, start, end)
    ts = timeseries(records, metric)
    return {"region": region, "metric": metric, "data": ts}


@app.get("/api/anomalies")
def anomalies_endpoint(
    region: str = Query("bay_of_bengal"),
):
    start, end = _default_range(5)
    records = get_occurrences_for_period(region, start, end)
    result  = detect_anomalies(records)
    return {"region": region, **result}


# ---------------------------------------------------------------------------
# POST /api/what-if
# ---------------------------------------------------------------------------
class WhatIfRequest(BaseModel):
    region: str = "bay_of_bengal"
    stressor_type: str = "temperature_rise"
    severity: float = 0.5
    target_year: int = 2035


@app.post("/api/what-if")
def what_if_endpoint(body: WhatIfRequest):
    start, end = _default_range(10)
    records = get_occurrences_for_period(body.region, start, end)
    result  = project_scenario(records, body.stressor_type, body.severity, body.target_year)
    return {"region": body.region, **result}


# ---------------------------------------------------------------------------
# GET /api/export — raw records as downloadable CSV
# ---------------------------------------------------------------------------
@app.get("/api/export")
def export_endpoint(
    region: str = Query("bay_of_bengal"),
    format: str = Query("csv"),
):
    start, end = _default_range(5)
    records = get_occurrences_for_period(region, start, end)

    if format.lower() != "csv":
        raise HTTPException(status_code=400, detail="Only csv format is supported")

    buf = io.StringIO()
    export_fieldnames = [
        "scientificName",
        "decimalLatitude",
        "decimalLongitude",
        "eventDate",
        "region",
        "sst",
        "depth",
        "occurrenceID",
    ]
    writer = csv.DictWriter(buf, fieldnames=export_fieldnames)
    writer.writeheader()
    for r in records:
        writer.writerow({
            "scientificName": r.get("scientificName", ""),
            "decimalLatitude": r.get("lat", ""),
            "decimalLongitude": r.get("lon", ""),
            "eventDate": r.get("date", ""),
            "region": region,
            "sst": r.get("sst", "") if r.get("sst") is not None else "",
            "depth": r.get("depth", "") if r.get("depth") is not None else "",
            "occurrenceID": r.get("id", ""),
        })

    buf.seek(0)
    region_label = get_region_labels().get(region, region)
    filename = f"oceanix_{region}_{date.today().isoformat()}.csv"

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# POST /api/upload — CSV validation, nothing stored
# ---------------------------------------------------------------------------
@app.post("/api/upload")
async def upload_endpoint(file: UploadFile = File(...)):
    contents = await file.read()
    try:
        text = contents.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded")

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = set(reader.fieldnames or [])

    # Check columns allowing aliases (lat->decimalLatitude, lon->decimalLongitude, date->eventDate)
    normalized_fields = set(fieldnames)
    if "lat" in normalized_fields:
        normalized_fields.add("decimalLatitude")
    if "lon" in normalized_fields:
        normalized_fields.add("decimalLongitude")
    if "date" in normalized_fields:
        normalized_fields.add("eventDate")

    missing = EXPECTED_CSV_COLUMNS - normalized_fields
    extra   = fieldnames - EXPECTED_CSV_COLUMNS - OPTIONAL_CSV_COLUMNS - {"lat", "lon", "date"}

    valid_rows = 0
    errors: list[str] = []

    for i, row in enumerate(reader, start=2):  # row 1 = header
        row_errors = []
        if not row.get("scientificName", "").strip():
            row_errors.append("missing scientificName")

        lat_val = row.get("decimalLatitude") if row.get("decimalLatitude") is not None else row.get("lat", "")
        lon_val = row.get("decimalLongitude") if row.get("decimalLongitude") is not None else row.get("lon", "")

        try:
            float(lat_val)
        except (ValueError, TypeError):
            row_errors.append("invalid decimalLatitude")
        try:
            float(lon_val)
        except (ValueError, TypeError):
            row_errors.append("invalid decimalLongitude")

        if row_errors:
            errors.append(f"Row {i}: {', '.join(row_errors)}")
        else:
            valid_rows += 1

    return {
        "filename": file.filename,
        "total_rows": valid_rows + len(errors),
        "valid_rows": valid_rows,
        "error_count": len(errors),
        "errors": errors[:20],  # cap error list for response size
        "missing_columns": list(missing),
        "extra_columns": list(extra),
        "expected_columns": list(EXPECTED_CSV_COLUMNS),
        "optional_columns": list(OPTIONAL_CSV_COLUMNS),
        "note": "File validated in-memory. No data was stored.",
    }


# ---------------------------------------------------------------------------
# POST /api/ask
# ---------------------------------------------------------------------------
class AskRequest(BaseModel):
    question: str
    region: Optional[str] = None


@app.post("/api/ask")
def ask_endpoint(body: AskRequest):
    result = assistant_ask(body.question, body.region)
    return result


# ---------------------------------------------------------------------------
# POST /api/translate
# ---------------------------------------------------------------------------
class TranslateRequest(BaseModel):
    text: str
    target_lang: str


@app.post("/api/translate")
def translate_endpoint(body: TranslateRequest):
    translated = translate_text(body.text, body.target_lang)
    return {"translated": translated, "target_lang": body.target_lang}


# ---------------------------------------------------------------------------
# GET /api/report — PDF download
# ---------------------------------------------------------------------------
@app.get("/api/report")
def report_endpoint(
    region: str = Query("bay_of_bengal"),
    period_a: str = Query(None),
    period_b: str = Query(None),
):
    # Defaults: period_a = 6-3 years ago, period_b = 3 years ago to today
    if not period_a:
        s, e = _default_range(6)
        _, mid = _default_range(3)
        period_a = f"{s}:{mid}"
    if not period_b:
        mid, end = _default_range(3)
        period_b = f"{mid}:{end}"

    pdf_bytes = generate_report(region, period_a, period_b)
    region_label = get_region_labels().get(region, region)
    filename = f"oceanix_report_{region}_{date.today().isoformat()}.pdf"

    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# GET /api/environmental — environmental data for region
# ---------------------------------------------------------------------------
@app.get("/api/environmental")
def environmental_endpoint(
    region: str = Query("bay_of_bengal"),
    start_date: Optional[str] = Query(None),
    end_date:   Optional[str] = Query(None),
):
    if not start_date or not end_date:
        start_date, end_date = _default_range(1)
    results = get_environmental_data(region, start_date, end_date)
    return {"region": region, "count": len(results), "data": results}


# ---------------------------------------------------------------------------
# Static files — serve frontend at /
# ---------------------------------------------------------------------------
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
