"""
usgs_client.py
Thin client for the USGS Water Services "instantaneous values" (iv) API.
No API key required. Docs: https://waterservices.usgs.gov/docs/instantaneous-values/
 
We request every parameter code our risk model understands and simply
use whichever ones the site actually reports back - this makes the app
work across many different monitoring stations without per-site config.
"""
 
import dataclasses
import requests
from risk_model import PARAM_CODES, RiskFactors
 
BASE_URL = "https://waterservices.usgs.gov/nwis/iv/"
SITE_SERVICE_URL = "https://waterservices.usgs.gov/nwis/site/"
 
# Not every parameter USGS returns is used by the risk model (e.g. gage height
# is useful context but isn't a RiskFactors field). Only pass through fields
# that RiskFactors actually accepts.
_RISK_FACTOR_FIELDS = {f.name for f in dataclasses.fields(RiskFactors)}
 
 
class USGSFetchError(Exception):
    pass
 
 
def _parse_rdb(text: str) -> list[dict]:
    """
    Parse USGS RDB (tab-delimited) output. Format:
      # comment lines starting with '#'
      col1\tcol2\tcol3...      <- header
      8n\t15s\t...             <- format/width line (skip)
      value1\tvalue2\t...      <- data rows
    """
    lines = [line for line in text.splitlines() if not line.startswith("#") and line.strip()]
    if len(lines) < 3:
        return []
    headers = lines[0].split("\t")
    rows = []
    for line in lines[2:]:  # skip header + format-width line
        fields = line.split("\t")
        if len(fields) != len(headers):
            continue
        rows.append(dict(zip(headers, fields)))
    return rows
 
 
def search_sites_by_name(state_code: str, name_query: str = "", limit: int = 20) -> list[dict]:
    """
    Find monitoring sites in a US state, optionally filtered by a partial,
    case-insensitive match on the site/station name (e.g. "mendota", "lake").
 
    USGS's site service requires a "major filter" (state, HUC, county, or
    bounding box) - there's no global free-text name search - so a state
    code is required here.
 
    Returns a list of dicts: {site_no, station_name, site_type, latitude, longitude}
    """
    params = {
        "format": "rdb",
        "stateCd": state_code,
        "parameterCd": ",".join(PARAM_CODES.keys()),
        "siteOutput": "expanded",
        "seriesCatalogOutput": "true",
        "outputDataTypeCd": "iv",
    }
 
    try:
        resp = requests.get(SITE_SERVICE_URL, params=params, timeout=20)
    except requests.RequestException as e:
        raise USGSFetchError(f"Network error contacting USGS site service: {e}")
 
    if resp.status_code != 200:
        raise USGSFetchError(f"USGS site service returned status {resp.status_code}: {resp.text[:300]}")
 
    rows = _parse_rdb(resp.text)
    if not rows:
        raise USGSFetchError(
            f"No real-time water-quality monitoring sites found for state '{state_code}'."
        )
 
    query_lower = name_query.strip().lower()
    seen_site_nos = set()
    matches = []
    for row in rows:
        site_no = row.get("site_no", "")
        station_nm = row.get("station_nm", "")
        if not site_no or site_no in seen_site_nos:
            continue
        if query_lower and query_lower not in station_nm.lower():
            continue
        seen_site_nos.add(site_no)
        try:
            lat = float(row.get("dec_lat_va", "") or "nan")
            lon = float(row.get("dec_long_va", "") or "nan")
        except ValueError:
            lat, lon = None, None
        matches.append({
            "site_no": site_no,
            "station_name": station_nm,
            "site_type": row.get("site_tp_cd", ""),
            "latitude": lat,
            "longitude": lon,
        })
        if len(matches) >= limit:
            break
 
    if not matches:
        raise USGSFetchError(
            f"No sites in state '{state_code}' matched the name '{name_query}'. "
            f"Try a shorter search term or a different state."
        )
 
    return matches
 
 
def fetch_site_data(site_no: str, period: str = "P1D") -> dict:
    """
    Fetch the most recent instantaneous readings for a site.
 
    Args:
        site_no: USGS site number, e.g. "09504500"
        period: ISO-8601-ish duration string USGS accepts, e.g. "P1D" (1 day),
                "P7D" (7 days). We only use the latest value per parameter.
 
    Returns:
        dict with keys: site_name, latitude, longitude, factors (RiskFactors),
        raw_readings (dict of param_code -> {value, datetime, unit})
    """
    params = {
        "format": "json",
        "sites": site_no,
        "parameterCd": ",".join(PARAM_CODES.keys()),
        "siteStatus": "all",
        "period": period,
    }
 
    try:
        resp = requests.get(BASE_URL, params=params, timeout=15)
    except requests.RequestException as e:
        raise USGSFetchError(f"Network error contacting USGS: {e}")
 
    if resp.status_code != 200:
        raise USGSFetchError(f"USGS API returned status {resp.status_code}: {resp.text[:300]}")
 
    data = resp.json()
    time_series = data.get("value", {}).get("timeSeries", [])
 
    if not time_series:
        raise USGSFetchError(
            f"No data returned for site {site_no}. The site may not exist, "
            f"may not report any of the tracked parameters, or may be offline."
        )
 
    site_name = None
    latitude = None
    longitude = None
    raw_readings = {}
    factor_kwargs = {}
 
    for series in time_series:
        source_info = series.get("sourceInfo", {})
        if site_name is None:
            site_name = source_info.get("siteName")
            geo = source_info.get("geoLocation", {}).get("geogLocation", {})
            latitude = geo.get("latitude")
            longitude = geo.get("longitude")
 
        var_codes = series.get("variable", {}).get("variableCode", [])
        if not var_codes:
            continue
        param_code = var_codes[0].get("value")
        field_name = PARAM_CODES.get(param_code)
        if field_name is None:
            continue
 
        values = series.get("values", [])
        if not values or not values[0].get("value"):
            continue
 
        latest = values[0]["value"][-1]  # most recent reading
        try:
            numeric_value = float(latest["value"])
        except (ValueError, TypeError):
            continue
 
        # USGS uses sentinel values like -999999 for missing data
        if numeric_value <= -999990:
            continue
 
        unit = series.get("variable", {}).get("unit", {}).get("unitCode", "")
        raw_readings[param_code] = {
            "field": field_name,
            "value": numeric_value,
            "datetime": latest.get("dateTime"),
            "unit": unit,
        }
        if field_name in _RISK_FACTOR_FIELDS:
            factor_kwargs[field_name] = numeric_value
 
    if not raw_readings:
        raise USGSFetchError(
            f"Site {site_no} was found but returned no usable readings for the "
            f"parameters this tool tracks (water temp, DO, pH, conductance, "
            f"turbidity, chlorophyll, streamflow)."
        )
 
    return {
        "site_no": site_no,
        "site_name": site_name,
        "latitude": latitude,
        "longitude": longitude,
        "factors": RiskFactors(**factor_kwargs),
        "raw_readings": raw_readings,
    }
 
 
if __name__ == "__main__":
    # Sanity check against a known-good site (requires network access)
    import json
    result = fetch_site_data("09504500")
    print(f"Site: {result['site_name']} ({result['latitude']}, {result['longitude']})")
    print(json.dumps(result["raw_readings"], indent=2))
