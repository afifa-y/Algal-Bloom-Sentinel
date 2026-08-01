"""
alert_generator.py
Turns a numeric risk score + raw sensor readings into a clear, actionable
alert written in plain language. This is the "AI as core component, not
a superficial add-on" part of the project: the risk_model.py score is
what triggers action, but a bare number ("score: 74") means nothing to
a park ranger, a water-authority staffer, or a member of the public.
An LLM turns that number + the underlying readings into an explanation
of WHY the risk is elevated and WHAT to do about it, tailored to the
audience that needs to read it.

Provider support (checked in this order, first available wins):
  1. Gemini  - GEMINI_API_KEY env var. FREE tier, no billing/credit card
               required. Get a key at https://aistudio.google.com/apikey
  2. Claude  - ANTHROPIC_API_KEY env var. Paid (small per-call cost).
  3. Offline template fallback - no API key, no internet call at all.
               Always works, guarantees the demo never breaks, but is
               a fixed template rather than a generated explanation.
"""

import os

AUDIENCE_PROMPTS = {
    "public_health_official": (
        "Write for a public health / water-authority official who needs to "
        "decide whether to dispatch a field team for water sampling. Be "
        "precise about the readings driving the risk score. Include a "
        "recommended action and a rough timeframe."
    ),
    "general_public": (
        "Write for a general public notice (e.g. posted at a park or lake "
        "access point, or shared on social media). Avoid jargon, keep it "
        "to 3-4 short sentences, and give clear practical guidance (e.g. "
        "avoid contact with water, keep pets out of the water)."
    ),
}


def _build_prompt(site_name, risk_score, risk_level, confidence, contributing_factors,
                   missing_factors, audience):
    factor_lines = []
    for field_name, info in contributing_factors.items():
        factor_lines.append(
            f"- {field_name}: {info['value']} (risk contribution {info['risk_contribution']}, weight {info['weight']})"
        )
    factor_text = "\n".join(factor_lines) if factor_lines else "No sensor readings available."
    missing_text = ", ".join(missing_factors) if missing_factors else "none"
    audience_instruction = AUDIENCE_PROMPTS.get(audience, AUDIENCE_PROMPTS["public_health_official"])

    return f"""You are an environmental early-warning assistant for a harmful algal bloom (HAB) monitoring system.

Site: {site_name}
Computed bloom risk score: {risk_score}/100 ({risk_level} risk, {confidence} confidence)

Sensor readings feeding this score:
{factor_text}

Sensor parameters NOT available for this site (missing data): {missing_text}

Task: {audience_instruction}

Ground every claim in the actual numbers above. Do not invent readings that
weren't provided. If confidence is Low or Medium, note that briefly rather
than overstating certainty. Do not use markdown headers or bullet points in
your output -- write it as prose suitable for direct posting or forwarding."""


def _generate_with_gemini(prompt: str, api_key: str) -> str:
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")
    response = model.generate_content(prompt)
    return response.text.strip()


def _generate_with_claude(prompt: str, api_key: str) -> str:
    from anthropic import Anthropic
    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in response.content if block.type == "text").strip()


def _generate_offline_template(site_name, risk_score, risk_level, confidence,
                                contributing_factors, missing_factors, audience) -> str:
    """No API key, no internet call. Guarantees the demo always has *something*
    to show, but this is a fixed template, not a generated explanation - use
    the Gemini or Claude path whenever possible for the real AI-usage story."""
    top_factors = sorted(
        contributing_factors.items(), key=lambda kv: kv[1]["risk_contribution"], reverse=True
    )[:3]
    factor_summary = ", ".join(f"{name} ({info['value']})" for name, info in top_factors) or "no readings available"

    if audience == "general_public":
        return (
            f"Water quality notice for {site_name}: current monitoring shows {risk_level.lower()} "
            f"bloom risk ({risk_score}/100, {confidence.lower()} confidence). Readings of concern: "
            f"{factor_summary}. Until conditions improve, avoid contact with the water and keep pets "
            f"out. [Offline template - no LLM key configured.]"
        )
    return (
        f"Bloom risk alert for {site_name}: score {risk_score}/100 ({risk_level}, {confidence} confidence). "
        f"Primary contributing factors: {factor_summary}. Missing sensor data: "
        f"{', '.join(missing_factors) if missing_factors else 'none'}. Recommend field sampling within "
        f"48-72 hours if risk remains elevated on next reading. [Offline template - no LLM key configured.]"
    )


def generate_alert(
    site_name: str,
    risk_score: float,
    risk_level: str,
    confidence: str,
    contributing_factors: dict,
    missing_factors: list,
    audience: str = "public_health_official",
) -> str:
    """
    Drafts a plain-language alert using whichever LLM provider has a key
    configured (Gemini free tier preferred, then Claude), falling back to
    an offline template if neither is available.
    """
    gemini_key = os.environ.get("GEMINI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    prompt = _build_prompt(
        site_name, risk_score, risk_level, confidence,
        contributing_factors, missing_factors, audience,
    )

    if gemini_key:
        return _generate_with_gemini(prompt, gemini_key)
    if anthropic_key:
        return _generate_with_claude(prompt, anthropic_key)

    return _generate_offline_template(
        site_name, risk_score, risk_level, confidence,
        contributing_factors, missing_factors, audience,
    )


if __name__ == "__main__":
    sample_factors = {
        "water_temp_c": {"value": 28, "risk_contribution": 0.8, "weight": 2.0},
        "ph": {"value": 8.9, "risk_contribution": 0.75, "weight": 1.5},
        "dissolved_oxygen_mg_l": {"value": 13.5, "risk_contribution": 0.7, "weight": 1.5},
    }
    alert = generate_alert(
        site_name="Test Lake",
        risk_score=75.1,
        risk_level="Severe",
        confidence="High",
        contributing_factors=sample_factors,
        missing_factors=["chlorophyll_ug_l", "turbidity_fnu"],
        audience="public_health_official",
    )
    print(alert)
