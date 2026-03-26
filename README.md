# Amazon Placement Optimizer

![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue) ![License: MIT-0](https://img.shields.io/badge/license-MIT--0-green) ![Platform: Amazon Ads](https://img.shields.io/badge/platform-Amazon%20Ads-orange)

Automatically tune your Amazon Sponsored Products and Sponsored Brands placement bid modifiers — Top of Search, Product Page, Rest of Search — based on actual ACOS performance data. Set your target ACOS range once; the tool does the math and shows you exactly what to change before anything touches your account.

---

## What does it actually do?

Amazon lets you adjust how aggressively you bid on different ad placements (e.g., bid 50% *more* on Top of Search, or 20% *less* on Product Pages). Most advertisers set these once and forget them.

This tool pulls your placement performance data for a date range you choose, compares each placement's ACOS to the target range you define, and recommends modifier adjustments — nudging each placement toward your goal proportionally. You review the changes in a browser UI before anything is applied.

**Example:** Your Top of Search ACOS is 42% and your target is 25–30%. The tool calculates a downward adjustment to your modifier and shows you the before/after. You click Apply when ready.

---

## How the formula works

For each campaign × placement combination:

1. **Compute the gap** — how far is the current ACOS from the midpoint of your target range?
2. **Apply dampening** — scale the adjustment to avoid overcorrecting (default: 50% of the raw signal). Large swings are split across runs.
3. **Clamp to limits** — modifiers are bounded between `min_modifier_pct` and `max_modifier_pct` in your config.
4. **Zero-out rule** — if a placement is significantly underperforming (ACOS > 2× target), the modifier is set to 0% (no uplift).
5. **Skip low-data placements** — if a placement has fewer than `min_clicks` clicks, no recommendation is made.

### Worked example

| Setting | Value |
|---|---|
| Target ACOS (NB) | 25–30% (midpoint: 27.5%) |
| Current Top of Search ACOS | 38% |
| Current Top of Search modifier | +60% |
| Dampening | 50% |

Gap = 38% − 27.5% = **10.5 percentage points** over target  
Raw adjustment = −10.5pp × 0.5 dampening = **−5.25pp**  
New modifier = 60% − 5.25% = **~55%** (rounded)

The tool shows: `+60% → +55% (−5pp)` — a controlled step in the right direction.

---

## Prerequisites

- **Python 3.9 or newer** — [download here](https://www.python.org/downloads/)
- **Amazon Ads API access** — you need a self-service API application approved by Amazon
  - Go to [advertising.amazon.com/API/access](https://advertising.amazon.com/API/access)
  - Create an application, note your **Client ID** and **Client Secret**
  - Your account must have at least one Sponsored Products or Sponsored Brands profile

> **No coding experience required** for setup and daily use — just follow the steps below.

---

## Quick Start

```bash
# 1. Install dependencies (one-time)
pip install -r requirements.txt

# 2. Copy credential template and fill in your Client ID + Secret
cp .env.example .env
# Open .env in any text editor and set ADS_CLIENT_ID and ADS_CLIENT_SECRET

# 3. Authenticate (opens a browser window — log in with your Amazon Ads account)
python run.py auth

# 4. Find your profile ID
python run.py list-profiles

# 5. Copy the config template and fill in your profile ID + ACOS targets
cp config/account.yaml.example config/account.yaml
# Open config/account.yaml and set profile_id, name, and ACOS target ranges

# 6. Run the optimizer (last 30 days, opens browser review UI)
python run.py start --days 30
```

---

## CLI Reference

| Command | What it does |
|---|---|
| `python run.py auth` | Opens a browser for Amazon OAuth login. Saves your refresh token to `.env`. Run once per account. |
| `python run.py list-profiles` | Lists all Amazon Ads profiles your credentials can access, with IDs and names. |
| `python run.py start` | Pulls placement data, computes recommendations, opens a browser review UI. |
| `python run.py status` | Check if a run is currently in progress. |

### `start` options

| Flag | Default | Description |
|---|---|---|
| `--days 30` | 30 | How many days of data to pull |
| `--start-date 2026-01-01` | — | Explicit start date (overrides `--days`) |
| `--end-date 2026-01-31` | — | Explicit end date (use with `--start-date`) |
| `--ad-type sp` | `both` | Which campaign types: `sp`, `sb`, or `both` |
| `--dry-run` | off | Compute and print recommendations; don't open browser or apply anything |
| `--no-browser` | off | Don't auto-open the browser UI |
| `--show-skipped` | off | Include low-data placements in the terminal output |

---

## Configuration reference (`config/account.yaml`)

Copy `config/account.yaml.example` to `config/account.yaml` and fill in these values:

```yaml
name: "My Account"           # A human-readable label — shown in the UI header
profile_id: "YOUR_PROFILE_ID_HERE"  # From `python run.py list-profiles`

# Non-branded (NB) campaigns — typically higher ACOS tolerance
nb_acos_low: 0.25            # Minimum acceptable ACOS for NB (e.g. 0.25 = 25%)
nb_acos_high: 0.35           # Maximum acceptable ACOS for NB (e.g. 0.35 = 35%)

# Branded campaigns — typically tighter ACOS target
brand_acos_low: 0.10         # Minimum acceptable ACOS for branded
brand_acos_high: 0.20        # Maximum acceptable ACOS for branded

# Placement modifier limits
min_modifier_pct: -90        # Never go below this modifier (e.g. -90 = reduce bids by 90%)
max_modifier_pct: 900        # Never go above this modifier (e.g. 900 = 9× bid uplift)

# Data quality threshold — placements with fewer clicks than this are skipped
min_clicks: 10

# Dampening — how aggressively to move each run (0.0–1.0)
# 0.5 = move 50% of the way toward target; lower = more conservative
dampening: 0.5

# Flag threshold — modifiers at or above this % are highlighted in the UI for review
flag_threshold_pct: 300

# Campaign name patterns used to classify branded vs. non-branded
# Any campaign matching these strings (case-insensitive) is treated as "brand"
brand_patterns:
  - "brand"
  - "branded"
```

**How branded vs. non-branded detection works:** The tool checks each campaign name against `brand_patterns`. A match = branded campaign, uses `brand_acos_*` targets. Everything else uses `nb_acos_*`. Add your brand name to the list (e.g., `"acme"`) for more precise detection.

---

## The Review UI

When a run completes, a browser page opens automatically at `http://localhost:8501`. From here you can:

- See every recommended change in a table: campaign, placement, current ACOS vs. target, old modifier → new modifier, delta
- Check or uncheck individual rows before applying
- Apply "safe" changes (within normal range) separately from ⚑ flagged ones (very high modifiers)
- Flagged changes are highlighted in yellow — review these before applying

Nothing is written to Amazon until you click **Apply**.

---

## FAQ

**Q: Do I need to be a developer to use this?**  
No. If you can run commands in a terminal and edit a text file, you can use this. The setup steps are a one-time effort; after that it's `python run.py start`.

**Q: Will this make changes automatically?**  
Never without your approval. Every run shows you what would change in a browser UI. You click Apply when ready. There's also a `--dry-run` flag that never touches anything.

**Q: How often should I run it?**  
Weekly is a good starting cadence. Daily is fine for high-spend accounts. The dampening setting prevents the optimizer from overcorrecting between runs.

**Q: What if a placement has very little data?**  
It's skipped. The `min_clicks` setting (default: 10) ensures recommendations are only made for placements with enough signal. Skipped placements are shown in a collapsible section in the UI.

**Q: What's a "flagged" change?**  
Any modifier the tool wants to set above `flag_threshold_pct` (default: 300%) is flagged with a ⚑ and highlighted yellow. This is a safeguard — very high modifiers can significantly spike spend. They're excluded from the default apply action so you review them intentionally.

**Q: Does this work for both Sponsored Products and Sponsored Brands?**  
Yes. Use `--ad-type sp`, `--ad-type sb`, or `--ad-type both` (default).

**Q: What placements does it optimize?**  
Top of Search, Product Page, and Rest of Search (and Home Page / Amazon Business if present on your account). Placements vary by ad type.

**Q: Is my data sent anywhere?**  
No. Everything runs locally on your machine. The tool talks directly to Amazon's Ads API using your credentials.

---

## File structure

```
.
├── run.py                      # CLI entry point
├── requirements.txt            # Python dependencies
├── .env.example                # Credential template (copy to .env)
├── config/
│   └── account.yaml.example   # Account config template (copy to account.yaml)
├── lib/
│   ├── ads_api.py              # Amazon Ads API client (OAuth, reporting, campaign updates)
│   ├── optimizer.py            # Placement formula logic
│   ├── worker.py               # Orchestration pipeline
│   ├── server.py               # Local review UI server
│   └── html_report.py          # HTML diff page renderer
└── output/                     # Run results saved here (auto-created)
```

---

## License

[MIT-0](https://opensource.org/licenses/MIT-0) — do whatever you want with it.
