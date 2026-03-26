---
name: amazon-placement-optimizer
description: Audit and optimize Amazon Ads placement bid modifiers (SP + SB) to goal-seek toward your target ACOS per placement. Pulls live placement performance data via the Amazon Ads API, computes recommendations using a dampened formula, shows a diff table for review, and applies approved changes — all from chat.
version: 1.0.0
metadata:
  openclaw:
    requires:
      env:
        - ADS_CLIENT_ID
        - ADS_CLIENT_SECRET
        - ADS_REFRESH_TOKEN
      bins:
        - python
    primaryEnv: ADS_CLIENT_ID
    install:
      - kind: node
        package: uv
        bins: [uv]
    emoji: "📊"
    homepage: https://github.com/shiftymix/amazonskills-placementmodifiers
---

# Amazon Placement Optimizer

Optimize Amazon Ads placement bid modifiers for Sponsored Products (SP) and Sponsored Brands (SB) campaigns — from chat, via the Amazon Ads API.

## What It Does

1. Pulls placement performance data (impressions, clicks, spend, sales) via the v3 Reporting API for a date range you specify
2. Loads current placement modifier % for each campaign via the v1 Campaign Management API
3. Computes recommended modifier adjustments using a goal-seek formula toward your target ACOS
4. Shows you a full diff table — no changes are made without your explicit approval
5. Applies approved changes in bulk via the API

Supports SP and SB campaigns. Works with a single Amazon Ads account or profile.

---

## First-Time Setup

See `SETUP.md` for step-by-step credential setup, including how to register for Amazon Ads API access, run OAuth, and find your profile ID.

**Quick start (after credentials are set):**
```bash
python run.py list-profiles        # find your profile ID
# edit config/account.yaml with your profile ID + ACOS targets
python run.py start --days 30      # run the optimizer
```

---

## Invoke

Say things like:
- "run placement optimizer for the last 30 days"
- "optimize placement modifiers MTD"
- "show placement recommendations, don't apply yet"
- "apply the placement changes we reviewed"

---

## Run Flow

### Step 1 — Confirm parameters

Before touching anything, confirm:

```
Running Amazon Placement Optimizer.
  • Profile: {profile_id} ({account_name})
  • Ad types: SP + SB
  • Date range: {start} to {end} ({N} days)
  • NB target ACOS range: {nb_low}%–{nb_high}%
  • Brand target ACOS range: {brand_low}%–{brand_high}%
  • Min clicks to adjust: {min_clicks}
  • Scope: all ENABLED campaigns

Confirm? (yes / adjust)
```

### Step 2 — Pull placement data

Run:
```bash
python run.py start --days 30 --ad-type both
```

This will:
- Request SP + SB placement performance reports via v3 Reporting API
- Poll until complete (can take 5–45 minutes for large accounts)
- Download and decompress report data
- Fetch current placement modifiers for all enabled campaigns via v1 API
- Compute recommendations
- Open interactive diff review at http://localhost:8501

### Step 3 — Review diff table

The browser UI shows:

| Campaign | Placement | Seg | ACOS | Target | Old % | New % | Δ |
|---|---|---|---|---|---|---|---|
| ... | ... | NB | 34% | 24% | 15% | 8% | -7pp |

Skipped placements (low clicks, no data) are listed separately with reason.

**No changes are applied until you click "Apply" in the UI.**

### Step 4 — Apply

Click **Apply Selected** (or **Apply All**) in the review UI.

Changes are applied via `POST /adsApi/v1/update/campaigns`. Results are logged to `output/run-YYYY-MM-DD.json`.

### Step 5 — Summary

After applying, a summary is posted:
```
Placement optimizer complete — {date range}
  X campaigns reviewed
  Y placements adjusted
  Z skipped (low data)
  W already on target
```

---

## Formula

```
new_modifier = [(1 + cur_modifier/100) × (target_acos / cur_acos) - 1] × 100
             × dampening_factor
```

Clamped to [0%, 900%]. Applied only when `clicks ≥ min_clicks`.

**Dampening** (configured per account):
- Base: 0.50 — moves 50% of the calculated delta per run
- High-modifier: extra conservative when current modifier ≥ threshold
- Max increase cap: limits how many percentage points can be added in a single run

**Zero-out rule:** if ACOS > zero-out threshold AND current modifier < zero-out max → set modifier to 0 (stop feeding an underperforming placement)

---

## Brand vs. Nonbrand Detection

Campaign name patterns (case-insensitive) in `config/account.yaml`:
```yaml
brand_patterns:
  - "Branded"
  - "Brand"
```

Campaigns matching any pattern use the brand ACOS target. All others use nonbrand.

---

## Files

| File | Purpose |
|---|---|
| `run.py` | CLI entry point |
| `lib/ads_api.py` | Amazon Ads API client (auth, reporting, campaign management) |
| `lib/optimizer.py` | Placement formula, data classes, diff computation |
| `lib/html_report.py` | HTML/browser diff review UI |
| `lib/worker.py` | Background report polling + processing |
| `lib/server.py` | Local web server for review UI |
| `config/account.yaml` | Your account config (profile ID, ACOS targets, rules) |
| `config/account.yaml.example` | Template to copy and fill in |
| `.env` | Credentials (never commit this) |
| `output/` | Run logs and results |

---

## CLI Reference

```
python run.py auth                     # OAuth flow — get refresh token
python run.py list-profiles            # list accessible profile IDs + names
python run.py start [options]          # run the optimizer
  --days N                             # lookback days (default: 30)
  --start-date YYYY-MM-DD              # explicit start date
  --end-date YYYY-MM-DD                # explicit end date
  --ad-type sp|sb|both                 # which campaigns (default: both)
  --dry-run                            # compute recommendations, do not apply
  --include-flagged                    # include high-modifier campaigns
  --report-id ID                       # resume a polling run by report ID
python run.py status                   # check status of a running job
```

---

## Requirements

- Python 3.10+
- Amazon Ads API access (see SETUP.md)
- `pip install -r requirements.txt`
