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
from usgs_client import fetch_site_data, USGSFetchError
from alert_generator import generate_alert

st.set_page_config(page_title="Algal Bloom Sentinel", page_icon="🌊", layout="centered")

st.title("🌊 Algal Bloom Sentinel")
st.caption(
    "Early-warning risk scoring for harmful algal blooms, built on live USGS "
    "water quality data and Claude-generated alerts."
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
        3. **Claude** turns the score and the underlying readings into a
           clear, audience-appropriate alert - because a number alone
           doesn't tell a park ranger or a resident what to actually do.
        """
    )

st.subheader("1. Choose a monitoring site")
st.caption(
    "Enter a USGS site number. Not every USGS gauge has water-quality sensors - "
    "streamflow-only sites will return limited data. Browse "
    "[WaterQualityWatch](https://waterwatch.usgs.gov/wqwatch/) to find active "
    "sites with temperature, DO, pH, conductance, and turbidity sensors, or use "
    "the [National Water Dashboard](https://dashboard.waterdata.usgs.gov/) to "
    "search near a specific lake or river."
)

default_site = "05114000"  # Souris River near Sherwood, ND - continuous DO/temp/conductance monitor
site_no = st.text_input("USGS site number", value=default_site)
period = st.selectbox(
    "Lookback window for latest readings",
    options=["P1D", "P3D", "P7D"],
    format_func=lambda p: {"P1D": "Last 1 day", "P3D": "Last 3 days", "P7D": "Last 7 days"}[p],
)

fetch_clicked = st.button("Fetch live data & compute risk", type="primary")

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
