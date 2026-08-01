"""
risk_model.py
Algal bloom risk scoring.

Harmful Algal Blooms (HABs) are driven mainly by three converging conditions:
  1. Warm water temperature (cyanobacteria thrive above ~20-25C)
  2. High nutrient load (proxied here by specific conductance / turbidity,
     since USGS real-time nutrient sensors are sparse)
  3. Stagnant / low-flow conditions (blooms need still water to accumulate)

This module implements a transparent, explainable weighted risk score
(0-100) rather than a black-box model. Each factor is scored 0-1 and
combined with domain-informed weights. This is intentional: for an
early-warning tool judges and water-authority end users need to be able
to see WHY a score is high, not just trust a number.

If historical bloom-occurrence labels are available for a site, a
logistic regression layer (train_classifier / predict_with_classifier)
can be trained on top of these same features for a data-driven score.
"""

from dataclasses import dataclass, field
from typing import Optional
import math


# USGS parameter codes we care about
PARAM_CODES = {
    "00010": "water_temp_c",
    "00300": "dissolved_oxygen_mg_l",
    "00095": "specific_conductance_us_cm",
    "63680": "turbidity_fnu",
    "00400": "ph",
    "32316": "chlorophyll_ug_l",  # rarely available in real-time, used if present
    "00060": "streamflow_cfs",
    "00065": "gage_height_ft",
}


@dataclass
class RiskFactors:
    water_temp_c: Optional[float] = None
    dissolved_oxygen_mg_l: Optional[float] = None
    specific_conductance_us_cm: Optional[float] = None
    turbidity_fnu: Optional[float] = None
    ph: Optional[float] = None
    chlorophyll_ug_l: Optional[float] = None
    streamflow_cfs: Optional[float] = None

    def available_fields(self):
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class RiskResult:
    score: float  # 0-100
    level: str  # "Low", "Moderate", "High", "Severe"
    contributing_factors: dict = field(default_factory=dict)
    missing_factors: list = field(default_factory=list)
    confidence: str = "Medium"


def _sigmoid_scale(value, midpoint, steepness):
    """Smoothly map a raw value to a 0-1 risk contribution."""
    return 1 / (1 + math.exp(-steepness * (value - midpoint)))


def _temp_risk(temp_c: float) -> float:
    # Cyanobacteria bloom risk rises sharply between 20C and 30C
    return _sigmoid_scale(temp_c, midpoint=24, steepness=0.35)


def _oxygen_risk(do_mg_l: float) -> float:
    # Blooms often coincide with oxygen supersaturation (daytime photosynthesis)
    # OR depletion (bloom die-off / decomposition). Score low-middle DO as risk too.
    if do_mg_l < 4:
        return 0.85  # hypoxic, consistent with bloom die-off
    if do_mg_l > 12:
        return 0.7  # supersaturated, consistent with active bloom photosynthesis
    return 0.15


def _conductance_risk(cond_us_cm: float) -> float:
    # Higher conductance can indicate nutrient/agricultural runoff loading
    return _sigmoid_scale(cond_us_cm, midpoint=500, steepness=0.004)


def _turbidity_risk(turb_fnu: float) -> float:
    return _sigmoid_scale(turb_fnu, midpoint=25, steepness=0.05)


def _ph_risk(ph: float) -> float:
    # Cyanobacteria blooms tend to push pH up (>8.5) via CO2 drawdown
    if ph >= 8.5:
        return 0.75
    if ph >= 8.0:
        return 0.4
    return 0.1


def _chlorophyll_risk(chl_ug_l: float) -> float:
    # Direct bloom biomass proxy when available - strongest signal
    return _sigmoid_scale(chl_ug_l, midpoint=20, steepness=0.15)


def _flow_risk(flow_cfs: float) -> float:
    # Low flow -> stagnant water -> higher bloom risk. Inverse relationship.
    return 1 - _sigmoid_scale(flow_cfs, midpoint=50, steepness=0.05)


# weight given to each factor when present (weights re-normalized over
# whatever factors are actually available for a given site)
WEIGHTS = {
    "chlorophyll_ug_l": 3.0,      # strongest direct signal
    "water_temp_c": 2.0,
    "ph": 1.5,
    "dissolved_oxygen_mg_l": 1.5,
    "specific_conductance_us_cm": 1.0,
    "turbidity_fnu": 1.0,
    "streamflow_cfs": 1.0,
}

RISK_FUNCS = {
    "water_temp_c": _temp_risk,
    "dissolved_oxygen_mg_l": _oxygen_risk,
    "specific_conductance_us_cm": _conductance_risk,
    "turbidity_fnu": _turbidity_risk,
    "ph": _ph_risk,
    "chlorophyll_ug_l": _chlorophyll_risk,
    "streamflow_cfs": _flow_risk,
}


def score_risk(factors: RiskFactors) -> RiskResult:
    available = factors.available_fields()
    all_fields = list(RISK_FUNCS.keys())
    missing = [f for f in all_fields if f not in available]

    if not available:
        return RiskResult(
            score=0.0,
            level="Unknown",
            contributing_factors={},
            missing_factors=missing,
            confidence="Low",
        )

    total_weight = sum(WEIGHTS[f] for f in available)
    weighted_sum = 0.0
    contributions = {}

    for field_name, value in available.items():
        risk_fn = RISK_FUNCS[field_name]
        raw_risk = risk_fn(value)  # 0-1
        weight = WEIGHTS[field_name]
        weighted_sum += raw_risk * weight
        contributions[field_name] = {
            "value": value,
            "risk_contribution": round(raw_risk, 2),
            "weight": weight,
        }

    normalized = weighted_sum / total_weight  # 0-1
    score = round(normalized * 100, 1)

    if score >= 70:
        level = "Severe"
    elif score >= 50:
        level = "High"
    elif score >= 30:
        level = "Moderate"
    else:
        level = "Low"

    # confidence reflects how much of our signal set we actually have
    coverage = len(available) / len(all_fields)
    if coverage >= 0.6:
        confidence = "High"
    elif coverage >= 0.3:
        confidence = "Medium"
    else:
        confidence = "Low"

    return RiskResult(
        score=score,
        level=level,
        contributing_factors=contributions,
        missing_factors=missing,
        confidence=confidence,
    )


if __name__ == "__main__":
    # quick sanity check with no network needed
    test_cases = [
        ("Healthy lake", RiskFactors(water_temp_c=18, dissolved_oxygen_mg_l=8, ph=7.4)),
        ("Bloom-risk lake", RiskFactors(
            water_temp_c=28, dissolved_oxygen_mg_l=13.5, ph=8.9,
            specific_conductance_us_cm=650, turbidity_fnu=40, streamflow_cfs=5,
        )),
        ("Active bloom (chlorophyll present)", RiskFactors(
            water_temp_c=27, chlorophyll_ug_l=45, ph=9.1, dissolved_oxygen_mg_l=14,
        )),
    ]
    for name, factors in test_cases:
        result = score_risk(factors)
        print(f"\n{name}: score={result.score} level={result.level} confidence={result.confidence}")
        for k, v in result.contributing_factors.items():
            print(f"   {k}: value={v['value']} contribution={v['risk_contribution']}")
