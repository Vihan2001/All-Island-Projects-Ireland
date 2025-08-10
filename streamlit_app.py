# All-Island Major Projects Dashboard (Python / Streamlit)
# ---------------------------------------------------------------
# Features
# - Streamlit UI with sidebar filters (sector, jurisdiction, min cost, search)
# - Load live data from:
#     1) Any GeoJSON FeatureCollection URL
#     2) ArcGIS FeatureServer layer URL (auto-appends a GeoJSON query)
# - Normalises fields (name, sector, cost, dates, coords, etc.)
# - Map with clustering (folium + MarkerCluster) — supports an OFFLINE basemap
# - Data table + CSV download
# - Built-in lightweight tests you can run from the sidebar
# ---------------------------------------------------------------

import json
import math
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
import streamlit as st
from folium import Map, Marker, Popup
from folium.plugins import MarkerCluster

# -----------------------------
# Seed data (starter examples)
# -----------------------------
SEED_PROJECTS: List[Dict[str, Any]] = [
    {
        "id": "metrolink",
        "name": "MetroLink (Dublin)",
        "sector": "Transport",
        "jurisdiction": "Ireland",
        "company": "National Transport Authority / TII",
        "status": "Planning",
        "cost": 9_500_000_000,
        "start": "2025-01-01",
        "end": "2035-12-31",
        "coords": (-6.262, 53.351),  # (lng, lat)
        "url": "https://www.metrolink.ie/",
    },
    {
        "id": "northsouth400kv",
        "name": "North–South 400kV Interconnector",
        "sector": "Energy",
        "jurisdiction": "Cross-border",
        "company": "EirGrid / SONI",
        "status": "Under construction",
        "cost": 350_000_000,
        "start": "2024-01-01",
        "end": "2027-12-31",
        "coords": (-6.786, 54.318),
        "url": "https://www.eirgrid.ie/community/projects-your-area/north-south-interconnector",
    },
    {
        "id": "belfastgcs",
        "name": "Belfast Grand Central Station",
        "sector": "Transport",
        "jurisdiction": "Northern Ireland",
        "company": "Translink / NITHCo",
        "status": "Operational (Phase 1)",
        "cost": 340_000_000,
        "start": "2019-01-01",
        "end": "2024-10-13",
        "coords": (-5.939, 54.594),
        "url": "https://www.translink.co.uk/bgcs",
    },
    {
        "id": "corklowerharbour",
        "name": "Cork Lower Harbour Drainage",
        "sector": "Water",
        "jurisdiction": "Ireland",
        "company": "Uisce Éireann",
        "status": "Complete",
        "cost": 500_000_000,
        "start": "2015-01-01",
        "end": "2025-01-01",
        "coords": (-8.339, 51.861),
        "url": "https://www.water.ie/projects/",
    },
    {
        "id": "dartplus",
        "name": "DART+ Programme",
        "sector": "Transport",
        "jurisdiction": "Ireland",
        "company": "Iarnród Éireann / NTA",
        "status": "Phased delivery",
        "cost": 3_000_000_000,
        "start": "2020-01-01",
        "end": "2032-12-31",
        "coords": (-6.183, 53.353),
        "url": "https://www.irishrail.ie/about-us/iarnrod-eireann-projects-and-investments",
    },
]

SECTORS = ["Transport", "Energy", "Water", "Other"]
JURISDICTIONS = ["Ireland", "Northern Ireland", "Cross-border"]

# -----------------------------
# Helpers
# -----------------------------
def money(n: float) -> str:
    try:
        import locale
        locale.setlocale(locale.LC_ALL, "en_IE.UTF-8")
        return locale.currency(n, grouping=True)
    except Exception:
        return f"€{int(round(n, 0)):,}"

def parse_date(v: Any) -> Optional[str]:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        ms = v if v > 1e12 else (v * 1000 if v > 1e9 else v)
        try:
            return datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%d")
        except Exception:
            return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d.strftime("%Y-%m-%d")
    except Exception:
        try:
            d = datetime.strptime(str(v), "%Y-%m-%d")
            return d.strftime("%Y-%m-%d")
        except Exception:
            return None

def _normalise_record(rec: Dict[str, Any]) -> Dict[str, Any]
