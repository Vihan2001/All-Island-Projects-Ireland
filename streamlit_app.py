# All-Island Major Projects Dashboard (Python / Streamlit)
# ---------------------------------------------------------------
# Features:
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

def _normalise_record(rec: Dict[str, Any]) -> Dict[str, Any]:
    lower = {str(k).lower(): v for k, v in rec.items()}

    def get_any(*keys):
        for k in keys:
            v = lower.get(k)
            if v not in (None, ""):
                return v
        return None

    name = get_any("name", "project", "project_name", "title", "scheme", "scheme_name") or "Untitled project"

    sector_raw = str(get_any("sector", "category", "theme") or "Other").lower()
    if any(x in sector_raw for x in ["transport", "rail", "road", "bus"]):
        sector = "Transport"
    elif any(x in sector_raw for x in ["energy", "grid", "renew"]):
        sector = "Energy"
    elif any(x in sector_raw for x in ["water", "wastewater", "drainage", "uisce"]):
        sector = "Water"
    else:
        sector = "Other"

    jurisdiction_raw = str(get_any("jurisdiction", "region", "country") or "").lower()
    if "northern" in jurisdiction_raw:
        jurisdiction = "Northern Ireland"
    elif any(x in jurisdiction_raw for x in ["ireland", "roi", "republic"]):
        jurisdiction = "Ireland"
    else:
        jurisdiction = "Ireland"

    company = str(get_any("company", "promoter", "sponsor", "client", "authority", "organisation", "organization") or "")
    status = str(get_any("status", "stage", "lifecycle", "phase") or "")

    cost = get_any("cost", "total_cost", "estimated_cost", "capex", "budget", "value")
    if isinstance(cost, str):
        cost_num = re.sub(r"[^0-9.\-]", "", cost)
        cost = float(cost_num) if cost_num else 0.0
    if not isinstance(cost, (int, float)):
        cost = 0.0

    start = parse_date(get_any("start", "start_date", "construction_start", "planned_start"))
    end = parse_date(get_any("end", "end_date", "completion", "planned_completion"))

    lat = get_any("lat", "latitude", "y")
    lng = get_any("lng", "lon", "long", "longitude", "x")

    return {
        "name": str(name),
        "sector": sector,
        "jurisdiction": jurisdiction,
        "company": company,
        "status": status,
        "cost": float(cost),
        "start": start,
        "end": end,
        "lat": float(lat) if lat not in (None, "") else None,
        "lng": float(lng) if lng not in (None, "") else None,
    }
def _feature_to_project(feature: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    props = feature.get("properties", {}) or {}
    geom = feature.get("geometry", {}) or {}
    n = _normalise_record(props)

    coords: Optional[Tuple[float, float]] = None
    if geom.get("type") == "Point":
        coords = tuple(geom.get("coordinates", [None, None]))  # (lng, lat)
    elif geom.get("type") in ("Polygon", "MultiPolygon"):
        try:
            coords_str = json.dumps(geom.get("coordinates", []))
            nums = [float(m.group()) for m in re.finditer(r"-?\d+\.?\d*", coords_str)]
            lngs = nums[::2]; lats = nums[1::2]
            if lngs and lats:
                min_lng, max_lng = min(lngs), max(lngs)
                min_lat, max_lat = min(lats), max(lats)
                coords = ((min_lng + max_lng) / 2.0, (min_lat + max_lat) / 2.0)
        except Exception:
            coords = None

    if coords is None and n.get("lng") is not None and n.get("lat") is not None:
        coords = (n["lng"], n["lat"])  # type: ignore

    if coords is None:
        return None

    pid = (
        props.get("id")
        or props.get("objectid")
        or props.get("globalid")
        or f"{n['name']}-{str(abs(hash(json.dumps(props, sort_keys=True))))[:6]}"
    )

    return {
        "id": str(pid),
        "name": n["name"],
        "sector": n["sector"],
        "jurisdiction": n["jurisdiction"],
        "company": n.get("company", ""),
        "status": n.get("status", ""),
        "cost": float(n.get("cost", 0.0)),
        "start": n.get("start"),
        "end": n.get("end"),
        "coords": coords,
        "url": props.get("url") or props.get("link") or props.get("source") or "",
    }

def build_arcgis_query(url: str) -> str:
    url = url.strip()
    if not url:
        return ""
    return url if "/query?" in url else url.rstrip("/") + "/query?where=1%3D1&outFields=*&f=geojson"

def load_geojson(url: str) -> List[Dict[str, Any]]:
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    fc = r.json()
    if not isinstance(fc, dict) or fc.get("type") != "FeatureCollection":
        raise ValueError("Not a GeoJSON FeatureCollection")
    out: List[Dict[str, Any]] = []
    for f in (fc.get("features") or []):
        p = _feature_to_project(f)
        if p is not None:
            out.append(p)
    return out

def merge_projects(existing: List[Dict[str, Any]], incoming: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_id: Dict[str, Dict[str, Any]] = {p["id"]: p for p in existing}
    for p in incoming:
        by_id[p["id"]] = p
    return list(by_id.values())

# -----------------------------
# Streamlit UI
# -----------------------------
st.set_page_config(page_title="All-Island Major Projects", layout="wide")
st.title("All-Island Major Projects (Python)")
st.caption("Energy · Water · Transport — Ireland & Northern Ireland")

with st.sidebar:
    st.header("Filters & Data")

    query = st.text_input("Search projects", "")
    col_a, col_b = st.columns(2)
    with col_a:
        pick_sectors = st.multiselect("Sectors", SECTORS, default=["Transport", "Energy", "Water"])
    with col_b:
        pick_juris = st.multiselect("Jurisdictions", JURISDICTIONS, default=JURISDICTIONS)

    min_cost_m = st.slider("Minimum cost (€/m)", 0, 10_000, 50, step=10)

    st.subheader("Live data sources")
    use_offline_basemap = st.checkbox(
        "Use offline basemap (no external tiles)",
        value=True,
        help="If your environment blocks map tiles, keep this on."
    )

    geojson_url = st.text_input("Generic GeoJSON URL (FeatureCollection)")
    if st.button("Load GeoJSON", type="primary", disabled=not bool(geojson_url)):
        try:
            projects = load_geojson(geojson_url)
            st.session_state.setdefault("ext_projects", [])
            st.session_state["ext_projects"] = merge_projects(st.session_state["ext_projects"], projects)
            st.success(f"Loaded {len(projects)} projects from GeoJSON")
        except Exception as e:
            st.error(f"Failed to load GeoJSON: {e}")

    arc_url = st.text_input("ArcGIS FeatureServer Layer URL (…/FeatureServer/0)")
    if st.button("Query ArcGIS", disabled=not bool(arc_url)):
        try:
            target = build_arcgis_query(arc_url)
            projects = load_geojson(target)
            st.session_state.setdefault("ext_projects", [])
            st.session_state["ext_projects"] = merge_projects(st.session_state["ext_projects"], projects)
            st.success(f"Loaded {len(projects)} projects from ArcGIS layer")
        except Exception as e:
            st.error(f"Failed to query ArcGIS: {e}")

    st.subheader("Diagnostics")
    run_tests_flag = st.checkbox("Run built-in tests", value=False)

ext_projects: List[Dict[str, Any]] = st.session_state.get("ext_projects", [])
all_projects = SEED_PROJECTS + ext_projects

filtered = [
    p for p in all_projects
    if (query.lower() in p["name"].lower())
    and (p["sector"] in pick_sectors or (p["sector"] == "Other" and len(pick_sectors) > 0))
    and (p["jurisdiction"] in pick_juris or p["jurisdiction"] == "")
    and (float(p.get("cost", 0)) / 1_000_000 >= float(min_cost_m))
    and isinstance(p.get("coords"), (list, tuple))
]

with st.sidebar:
    total_cost = sum(float(p.get("cost", 0)) for p in filtered)
    st.info(
        f"Showing **{len(filtered)}** of {len(all_projects)} projects\n\n"
        f"Total cost (shown): **{money(total_cost)}**",
        icon="ℹ️"
    )

# Map -----------------------------------------------------------
if filtered:
    avg_lng = sum(p["coords"][0] for p in filtered) / len(filtered)
    avg_lat = sum(p["coords"][1] for p in filtered) / len(filtered)
else:
    avg_lng, avg_lat = (-7.6, 53.5)

if use_offline_basemap:
    folium_map = Map(location=(avg_lat, avg_lng), zoom_start=6, tiles=None, control_scale=True)
else:
    folium_map = Map(location=(avg_lat, avg_lng), zoom_start=6, tiles="OpenStreetMap", control_scale=True)

cluster = MarkerCluster(name="Projects").add_to(folium_map)

for p in filtered:
    lng, lat = p["coords"]
    html = f"""
    <div style='font-family: system-ui, sans-serif; font-size: 12px;'>
      <div style='font-weight:600;margin-bottom:4px'>{p['name']}</div>
      <div><b>Sector:</b> {p['sector']} &nbsp; <b>Jurisdiction:</b> {p['jurisdiction']}</div>
      <div><b>Company:</b> {p.get('company','')}</div>
      <div><b>Status:</b> {p.get('status','')}</div>
      <div><b>Cost:</b> {money(float(p.get('cost',0)))}</div>
      <div><b>Timeline:</b> {p.get('start') or '—'} – {p.get('end') or '—'}</div>
      {f"<div><a href='{p.get('url')}' target='_blank' rel='noreferrer'>Official page ↗</a></div>" if p.get('url') else ''}
    </div>
    """
    popup = Popup(html, max_width=360)
    Marker(location=(lat, lng), popup=popup).add_to(cluster)

st.components.v1.html(folium_map._repr_html_(), height=620)

# Table & download ---------------------------------------------
df = pd.DataFrame([
    {
        "id": p["id"],
        "name": p["name"],
        "sector": p["sector"],
        "jurisdiction": p["jurisdiction"],
        "company": p.get("company", ""),
        "status": p.get("status", ""),
        "cost": float(p.get("cost", 0)),
        "start": p.get("start"),
        "end": p.get("end"),
        "lat": p["coords"][1] if p.get("coords") else None,
        "lng": p["coords"][0] if p.get("coords") else None,
        "url": p.get("url", ""),
    }
    for p in filtered
])

st.subheader("Projects table")
st.dataframe(df, use_container_width=True)

csv = df.to_csv(index=False).encode("utf-8")
st.download_button("Download CSV", data=csv, file_name="projects_filtered.csv", mime="text/csv")

# -----------------------------
# Tests
# -----------------------------
def run_tests() -> None:
    # Seed checks
    assert isinstance(SEED_PROJECTS, list) and len(SEED_PROJECTS) >= 1
    for p in SEED_PROJECTS:
        assert p["id"] and p["name"]
        assert p["sector"] in ["Transport", "Energy", "Water"]
        assert isinstance(p["coords"], (list, tuple)) and len(p["coords"]) == 2
        lng, lat = p["coords"]
        assert -11 <= lng <= -5
        assert 51 <= lat <= 56
        assert isinstance(p["cost"], (int, float)) and p["cost"] > 0

    # Normaliser tests
    rec = _normalise_record({
        "Project_Name": "Test Rail",
        "Category": "Rail Transport",
        "total_cost": "€123.4m",
        "Start_Date": "2027-06-01",
        "Latitude": 53.3,
        "Longitude": -6.2,
    })
    assert rec["name"] == "Test Rail"
    assert rec["sector"] == "Transport"
    assert math.isclose(rec["cost"], 123.4, rel_tol=1e-6)
    assert rec["start"] == "2027-06-01"
    assert rec["lat"] == 53.3 and rec["lng"] == -6.2

    # ArcGIS builder
    assert build_arcgis_query("https://x/FeatureServer/0").endswith("/query?where=1%3D1&outFields=*&f=geojson")
    assert "/query?where=1%3D1" in build_arcgis_query("https://x/FeatureServer/0/query?where=1%3D1")

    # Polygon centroid test
    poly = {
        "type": "Feature",
        "properties": {"i
