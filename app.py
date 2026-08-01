"""
app.py
Algal Bloom Sentinel - Streamlit dashboard
 
Run with: streamlit run app.py
 
AI-generated alerts work with either:
  - GEMINI_API_KEY (recommended - free tier, no billing required.
    Get one at https://aistudio.google.com/apikey)
  - ANTHROPIC_API_KEY (paid, small per-call cost)
If neither is set, alerts fall back to a fixed offline template so the
app never fully breaks - but a real key is recommended for the demo.
The USGS data lookup works without any API key regardless.
"""
 
import os
 
import streamlit as st
from risk_model import score_risk
from usgs_client import fetch_site_data, search_sites_by_name, USGSFetchError
from alert_generator import generate_alert
 
US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
 
st.set_page_config(page_title="Algal Bloom Sentinel", page_icon="🌊", layout="centered")
 
st.title("🌊 Algal Bloom Sentinel")
st.caption(
    "Early-warning risk scoring for harmful algal blooms, built on live USGS "
    "water quality data and AI-generated alerts."
)
 
with st.expander("How this works", expanded=False):
    st.markdown(
        """
        1. **Live data** is pulled from the USGS Water Services API for the
           monitoring station you choose (water temperature, dissolved
           oxygen, pH, conductance, turbidity, streamflow, and chlorophyll
           where available).
        2. A **transparent risk model** (`risk_model.py`) combines these
           readings into a 0-100 bloom risk score using domain-informed
           weights, so the score is explainable rather than a black box.
        3. An **LLM** turns the score and the underlying readings into a
           clear, audience-appropriate alert - because a number alone
           doesn't tell a park ranger or a resident what to actually do.
        """
    )
 
st.subheader("1. Choose a monitoring site")
st.caption(
    "This tool only covers USGS-monitored sites, which are US-based. Not every "
    "site has water-quality sensors - streamflow-only sites will return limited data."
)
 
search_tab, manual_tab = st.tabs(["🔎 Search by name", "🔢 Enter site number"])
 
site_no = None
 
with search_tab:
    col1, col2 = st.columns([1, 2])
    with col1:
        state_code = st.selectbox(
            "State", options=list(US_STATES.keys()),
            format_func=lambda code: f"{code} - {US_STATES[code]}",
            index=list(US_STATES.keys()).index("WI"),
        )
    with col2:
        name_query = st.text_input("Lake or river name contains...", value="lake", placeholder="e.g. Mendota, Erie, Mississippi")
 
    if st.button("Search"):
        with st.spinner(f"Searching USGS sites in {US_STATES[state_code]}..."):
            try:
                results = search_sites_by_name(state_code, name_query)
                st.session_state["search_results"] = results
            except USGSFetchError as e:
                st.error(str(e))
                st.session_state.pop("search_results", None)
 
    if "search_results" in st.session_state:
        results = st.session_state["search_results"]
        options = {f"{r['station_name']} ({r['site_no']})": r["site_no"] for r in results}
        chosen_label = st.selectbox("Matching sites", options=list(options.keys()))
        site_no = options[chosen_label]
 
with manual_tab:
    st.caption(
        "If you already know a USGS site number, enter it directly. Browse "
        "[WaterQualityWatch](https://waterwatch.usgs.gov/wqwatch/) or the "
        "[National Water Dashboard](https://dashboard.waterdata.usgs.gov/) to find one."
    )
    manual_site_no = st.text_input("USGS site number", value="05114000")
    if manual_site_no:
        site_no = manual_site_no
 
period = st.selectbox(
    "Lookback window for latest readings",
    options=["P1D", "P3D", "P7D"],
    format_func=lambda p: {"P1D": "Last 1 day", "P3D": "Last 3 days", "P7D": "Last 7 days"}[p],
)
 
fetch_clicked = st.button("Fetch live data & compute risk", type="primary", disabled=not site_no)
 
if fetch_clicked:
    with st.spinner("Contacting USGS Water Services..."):
        try:
            site_data = fetch_site_data(site_no, period=period)
            st.session_state["site_data"] = site_data
        except USGSFetchError as e:
            st.error(str(e))
            st.session_state.pop("site_data", None)
 
if "site_data" in st.session_state:
    site_data = st.session_state["site_data"]
    st.success(f"Data loaded for **{site_data['site_name']}** (site {site_data['site_no']})")
 
    if site_data["latitude"] and site_data["longitude"]:
        st.map(
            data=[{"lat": site_data["latitude"], "lon": site_data["longitude"]}],
            zoom=9,
        )
 
    st.subheader("2. Current readings")
    reading_cols = st.columns(3)
    readable_labels = {
        "water_temp_c": ("Water temp", "°C"),
        "dissolved_oxygen_mg_l": ("Dissolved oxygen", "mg/L"),
        "ph": ("pH", ""),
        "specific_conductance_us_cm": ("Conductance", "µS/cm"),
        "turbidity_fnu": ("Turbidity", "FNU"),
        "chlorophyll_ug_l": ("Chlorophyll", "µg/L"),
        "streamflow_cfs": ("Streamflow", "ft³/s"),
    }
    i = 0
    for param_code, reading in site_data["raw_readings"].items():
        label, unit = readable_labels.get(reading["field"], (reading["field"], ""))
        with reading_cols[i % 3]:
            st.metric(label, f"{reading['value']} {unit}")
        i += 1
 
    st.subheader("3. Bloom risk score")
    result = score_risk(site_data["factors"])
    st.session_state["risk_result"] = result
 
    level_colors = {
        "Low": "green", "Moderate": "orange", "High": "red", "Severe": "red", "Unknown": "gray",
    }
    color = level_colors.get(result.level, "gray")
    st.markdown(f"### Risk: :{color}[{result.level}]  ({result.score}/100)")
    st.progress(min(result.score / 100, 1.0))
    st.caption(f"Confidence: {result.confidence} (based on {len(result.contributing_factors)} of "
               f"{len(result.contributing_factors) + len(result.missing_factors)} tracked parameters "
               f"being available for this site)")
 
    with st.expander("What's driving this score?"):
        for field_name, info in result.contributing_factors.items():
            label = readable_labels.get(field_name, (field_name, ""))[0]
            st.write(f"**{label}**: {info['value']} → risk contribution {info['risk_contribution']} "
                     f"(weight {info['weight']})")
        if result.missing_factors:
            st.caption(f"Not available at this site: {', '.join(result.missing_factors)}")
 
    st.subheader("4. AI-generated alert")
    gemini_set = bool(os.environ.get("GEMINI_API_KEY"))
    anthropic_set = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if gemini_set:
        st.caption("Using Gemini (free tier) to generate alerts.")
    elif anthropic_set:
        st.caption("Using Claude to generate alerts.")
    else:
        st.caption(
            "No LLM API key detected - alerts will use a fixed offline template. "
            "Set GEMINI_API_KEY (free, no billing required - get one at "
            "https://aistudio.google.com/apikey) or ANTHROPIC_API_KEY for a real "
            "AI-generated alert."
        )
    audience = st.radio(
        "Generate alert for:",
        options=["public_health_official", "general_public"],
        format_func=lambda a: {"public_health_official": "Water authority / official",
                                "general_public": "General public notice"}[a],
        horizontal=True,
    )
 
    if st.button("Generate alert with Claude"):
        with st.spinner("Asking Claude to draft the alert..."):
            try:
                alert_text = generate_alert(
                    site_name=site_data["site_name"],
                    risk_score=result.score,
                    risk_level=result.level,
                    confidence=result.confidence,
                    contributing_factors=result.contributing_factors,
                    missing_factors=result.missing_factors,
                    audience=audience,
                )
                st.info(alert_text)
            except RuntimeError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"Couldn't generate alert: {e}")
 
st.divider()
st.caption(
    "Built for AI 4 Earth Hackathon. Data source: USGS Water Services (public domain). "
    "This is a decision-support prototype, not a substitute for official water testing."
)
