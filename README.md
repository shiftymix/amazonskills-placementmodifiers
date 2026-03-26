# Amazon Placement Optimizer

![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue) ![License: MIT-0](https://img.shields.io/badge/license-MIT--0-green) ![Platform: Amazon Ads](https://img.shields.io/badge/platform-Amazon%20Ads-orange)

An open-source tool that tunes Amazon Sponsored Products and Sponsored Brands placement bid modifiers using actual performance data — and **learns your preferences over time**.

Every recommendation is reviewable in a browser UI before anything touches your account. You can override any value, skip rows, add notes — and those decisions are remembered. The more you use it, the more it reflects how *you* manage the account, not just what the formula suggests.

---

## The feedback loop: how it learns

Most optimizers are fire-and-forget. This one isn't.

After each run, you see a table of recommended changes. In the **New Mod% column, every value is editable** — type your own number if you disagree with the suggestion. Add a note explaining why. Skip rows you want to leave alone. Then save.

Those decisions are written to `output/overrides.json`. The **next time you run the optimizer**, your overrides come back pre-loaded. Your skips stay skipped. Your notes stay visible. If the formula suggests a change you've overridden before, you'll see your previous value, not the raw recommendation.

Over weeks of use, the review page becomes a record of your judgment for that account — which placements you're aggressive on, which ones you're cautious about, which campaigns you never touch. That context survives sessions, survives re-runs, and survives restarting your computer.

**This is the actual workflow:**

1. Run → review → override where needed → save → apply
2. Next week: run again → your previous notes and overrides are already there
3. The algorithm handles the math; you handle the strategy

---

## What does it do?

Amazon lets you adjust how aggressively you bid on different ad placements — Top of Search, Product Page, Rest of Search. Most advertisers set these once and forget them.

This tool pulls your placement performance data for a date range you choose, compares each placement's ACOS to the target range you define, and computes modifier adjustments. You review everything in an editable browser UI before any change reaches Amazon.

---

## How the formula works

For each campaign × placement combination:

1. **Compute the gap** — how far is the current ACOS from the midpoint of your target range?
2. **Apply dampening** — scale the adjustment to avoid overcorrecting (default: 50%). Large swings are split across runs.
3. **Clamp to limits** — modifiers stay within `min_modifier_pct` and `max_modifier_pct`.
4. **Zero-out rule** — if ACOS is way above target and the modifier is already low, set it to 0%.
5. **Skip low-data** — placements with fewer than `min_clicks` clicks get no recommendation.

### Worked example

| | Value |
|---|---|
| Target ACOS | 25–30% (midpoint 27.5%) |
| Current Top of Search ACOS | 38% |
| Current modifier | +60% |
| Dampening | 50% |

Gap = 38% − 27.5% = 10.5pp over target  
Adjustment = −10.5pp × 0.5 = −5.25pp  
New modifier = **55%** (rounded)

The UI shows: `+60% → +55% (−5pp)` — a controlled step. You can accept it, type 50% instead, or skip the row entirely.

---

## Prerequisites

- **Python 3.9 or newer** — [download here](https://www.python.org/downloads/)
- **Amazon Ads API credentials** — self-service application from Amazon
  - Go to [advertising.amazon.com/API/access](https://advertising.amazon.com/API/access)
  - Create an application — note your **Client ID** and **Client Secret**
  - Must have at least one Sponsored Products or Sponsored Brands profile

> **No coding experience required** for setup and daily use.

---

## Quick Start

```bash
# 1. Install dependencies (one-time)
pip install -r requirements.txt

# 2. Copy credential template and fill in Client ID + Secret
cp .env.example .env
# Edit .env with any text editor

# 3. Authenticate — opens a browser, log in with your Amazon Ads account
python run.py auth

# 4. Find your profile ID
python run.py list-profiles

# 5. Configure your account
cp config/account.yaml.example config/account.yaml
# Edit config/account.yaml — set profile_id and your ACOS targets

# 6. Run
python run.py start --days 30
```

---

## The Review UI

When a run completes, your browser opens to `http://localhost:8501`.

| Column | What it is |
|---|---|
| ✕ | Skip checkbox — checked rows are excluded from apply |
| Campaign | Campaign name |
| Placement | Top of Search, Product Page, Rest of Search, etc. |
| Type | SP (Sponsored Products) or SB (Sponsored Brands) |
| Seg | NB (non-branded) or Brand |
| Spend / Sales / Clicks | Performance data for the date range |
| ACOS% | Current ACOS — red if above target, green if below |
| Target | Your ACOS target range from config |
| Cur Mod% | Current placement modifier on this campaign |
| **New Mod% ✏** | **Recommended modifier — you can edit this** |
| Note | Free-text field for your reasoning |

**Two-step flow:**
1. **Save Edits** — writes your overrides to `output/overrides.json`
2. **Apply to Amazon** — pushes only the non-skipped rows to the Ads API

Nothing reaches Amazon until you click Apply.

---

## CLI Reference

| Command | What it does |
|---|---|
| `python run.py auth` | OAuth flow — opens browser, saves refresh token to `.env` |
| `python run.py list-profiles` | Lists all accessible profile IDs with names |
| `python run.py start` | Runs the optimizer, opens review UI |
| `python run.py status` | Check if a run is in progress |

### `start` options

| Flag | Default | Description |
|---|---|---|
| `--days 30` | 30 | Lookback window |
| `--start-date 2026-01-01` | — | Explicit start (overrides `--days`) |
| `--end-date 2026-01-31` | — | Explicit end |
| `--ad-type sp\|sb\|both` | `both` | Campaign types to optimize |
| `--dry-run` | off | Compute only — no browser, no apply |
| `--no-browser` | off | Don't auto-open browser |
| `--show-skipped` | off | Show low-data placements in terminal output |

---

## Configuration reference (`config/account.yaml`)

Copy `config/account.yaml.example` → `config/account.yaml`.

```yaml
name: "My Account"               # Label shown in the review UI
profile_id: "YOUR_PROFILE_ID"    # From `python run.py list-profiles`

# ACOS targets — the range you want each placement to land in
nb_acos_low:   0.25   # Minimum acceptable ACOS for non-branded campaigns (25%)
nb_acos_high:  0.35   # Maximum acceptable ACOS for non-branded campaigns (35%)
brand_acos_low:  0.10 # Minimum for branded campaigns
brand_acos_high: 0.20 # Maximum for branded campaigns

# Adjustment limits
min_modifier_pct: -90   # Never go below this modifier
max_modifier_pct: 900   # Never go above this (9× bid uplift)
max_increase_pp:  20    # Max increase per run in percentage points

# Data quality
min_clicks: 10          # Skip placements with fewer clicks than this

# Dampening — 0.5 = move 50% of the way toward target per run
# Lower = more conservative; higher = faster but riskier
dampening: 0.5
brand_dampening: 0.65

# Flagging — modifiers at or above this % are highlighted amber
flag_threshold_pct: 300

# Campaign name patterns for branded detection
# Any campaign name containing these strings (case-insensitive) = branded
brand_patterns:
  - "brand"
  - "branded"
  # Add your brand name here, e.g. "acme"
```

**Branded vs. non-branded:** campaigns matching `brand_patterns` use `brand_acos_*` targets. Everything else uses `nb_acos_*`. Add your brand name to the list for accurate segmentation.

---

## Overrides file (`output/overrides.json`)

This file is the tool's memory. It stores your per-row decisions:

```json
{
  "CAMPAIGN_ID|PLACEMENT": {
    "modifier_pct": 45,
    "skip": false,
    "note": "keep this low — competitor in this slot"
  }
}
```

- Automatically loaded every time you open the review UI
- Updated when you click "Save Edits"
- Safe to commit to version control — it's your account's strategy record
- Delete it to start fresh

---

## FAQ

**Q: Do I need to be a developer to use this?**  
No. Terminal + text editor is all you need. Setup is a one-time thing; after that it's `python run.py start`.

**Q: Will it make changes without asking me?**  
Never. Every change goes through the browser review UI. You click Apply. There's also `--dry-run` for zero-risk exploration.

**Q: What's a "flagged" row?**  
Any modifier above `flag_threshold_pct` (default 300%) is highlighted amber with a ⚠. High modifiers can spike spend. They're not excluded automatically — just surfaced for your attention.

**Q: How often should I run it?**  
Weekly for most accounts. Daily for high-spend. The dampening setting prevents overcorrection between runs.

**Q: What if I always override a certain campaign the same way?**  
Skip it once and save — it'll stay skipped. Add a note so you remember why. Next run, it comes back pre-skipped with your note.

**Q: Can I use this for multiple accounts?**  
Yes — maintain separate `config/account.yaml` and `output/` directories per account, or use `--config` (coming in a future release).

**Q: Does it work for both SP and SB?**  
Yes. Use `--ad-type sp`, `--ad-type sb`, or `--ad-type both` (default).

**Q: Is my data sent anywhere?**  
No. Runs entirely on your machine, talks directly to Amazon's API.

---

## File structure

```
.
├── run.py                      # CLI entry point
├── requirements.txt
├── .env.example                # Credential template → copy to .env
├── config/
│   └── account.yaml.example   # Account config template → copy to account.yaml
├── lib/
│   ├── ads_api.py              # Amazon Ads API: OAuth, reporting, campaign updates
│   ├── optimizer.py            # Placement formula + recommendation builder
│   ├── worker.py               # Pipeline: report request → poll → download → merge → recs
│   ├── server.py               # Local review server (port 8501)
│   └── html_report.py          # Editable diff UI renderer
└── output/
    ├── overrides.json          # Your saved edits and notes (the memory file)
    └── recs-*.json             # Run outputs
```

---

## License

[MIT-0](https://opensource.org/licenses/MIT-0) — do whatever you want with it.
