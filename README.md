Algal Bloom Sentinel 🌊
An early-warning system for harmful algal blooms (HABs), built for the AI 4 Earth Hackathon.
The problem
Harmful algal blooms contaminate drinking water, kill fish and wildlife, and can produce
toxins dangerous to people and pets. They're usually noticed only after the water visibly
turns green, or after someone gets sick — by which point remediation is expensive and the
damage to the ecosystem is already done. The conditions that precede a bloom (warm water,
high nutrient load, stagnant flow) are measurable before the bloom becomes visible.
The solution
Algal Bloom Sentinel pulls live water-quality readings from a public USGS monitoring
station, computes an explainable 0–100 bloom-risk score from those readings, and uses
Claude to translate that score into a plain-language alert for either a water authority
official or the general public.
How AI is used (and why it matters)
Risk scoring (`risk_model.py`) — a transparent, weighted model that combines water
temperature, dissolved oxygen, pH, conductance, turbidity, streamflow, and chlorophyll
(when available) into a single risk score. It's intentionally explainable rather than a
black box: for an early-warning tool, the people who'd actually use this need to see
why a score is high, not just trust a number. This is the "predictive model"
component — it's what lets the system act before a bloom is visible, not after.
Alert generation (`alert_generator.py`, via the Claude API) — a risk score alone
("74/100") doesn't tell a park ranger or a resident what's actually happening or what
to do. Claude takes the score plus the underlying sensor readings and drafts a
grounded, audience-appropriate alert (technical detail for officials deciding whether
to dispatch a field team; plain, actionable language for a public notice). This is
where AI moves the system from "here's a number" to "here's what you should do."
Architecture
```
USGS Water Services API  --->  risk_model.py  --->  alert_generator.py (Claude)
  (live sensor data)          (explainable ML)         (plain-language alert)
                                      |
                                      v
                              app.py (Streamlit UI)
```
Setup
```bash
pip install -r requirements.txt
```
Then set one of these (Gemini is recommended — it's free, no credit card):
Option A — Gemini (free, no billing required):
```bash
export GEMINI_API_KEY="your-key-here"   # get one at https://aistudio.google.com/apikey
```
Option B — Claude (paid, small per-call cost):
```bash
export ANTHROPIC_API_KEY="your-key-here"   # get one at https://console.anthropic.com/
```
Then run:
```bash
streamlit run app.py
```
The USGS data lookup and risk scoring work without any API key at all — only the
"Generate alert with Claude" button needs one of the two keys above. If neither is set,
the app falls back to a fixed offline template so the demo never fully breaks, but a real
key is strongly recommended so the alert is actually AI-generated for your demo.
Finding a USGS site number to test with
Not every USGS gauge has water-quality sensors — many only measure streamflow. To find an
active site with temperature/DO/pH/conductance sensors:
Browse WaterQualityWatch (real-time water-quality
monitoring map), or
Use the National Water Dashboard and search near
a specific lake or river, then copy the site number (e.g. `05114000`) into the app.
Roadmap (how this fits the larger "Earth Digital Immune System" vision)
This build focuses on one detection pipeline end-to-end, deliberately scoped for a
hackathon timeline. The same pattern — live sensor/imagery feed → explainable risk model →
LLM-generated alert — extends to other environmental threats:
Wildfire/deforestation: satellite imagery change-detection instead of water sensors
Illegal dumping: NLP classification of citizen/social reports instead of USGS data
Flooding: streamflow + precipitation forecasting instead of bloom-specific factors
Each pipeline would plug into the same "risk model → LLM alert" pattern demonstrated here.
Limitations & honesty notes
This is a decision-support prototype, not a substitute for official water testing or
regulatory bloom advisories.
Real-time chlorophyll sensors (the strongest direct bloom signal) are only available at
a subset of USGS sites; the model degrades gracefully (lower confidence) when they're
missing, using the other correlated factors instead.
The risk model's weights and thresholds are domain-informed but not fitted to labeled
historical bloom data. With more time, a logistic regression or gradient-boosted model
trained on historical bloom occurrence records (e.g. from state DNR bloom advisory
archives) could replace or augment the rule-based score
