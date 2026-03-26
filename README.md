# Amazon Placement Optimizer

![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue) ![License: MIT-0](https://img.shields.io/badge/license-MIT--0-green) ![Platform: Amazon Ads](https://img.shields.io/badge/platform-Amazon%20Ads-orange)

---

## TL;DR

**What:** A local CLI that pulls your Amazon placement performance data, computes bid modifier adjustments for each campaign × placement, and shows you a browser-based diff table before anything changes.

**How it works in 4 steps:**
1. Authenticate once with Amazon Ads API → run `python run.py start`
2. Tool fetches SP and/or SB placement reports + current modifiers via the API
3. Formula computes adjustments based on your ACOS targets (with dampening so it doesn't overcorrect)
4. Browser UI opens — you review, edit values, add notes, skip rows — then click Apply

**The real feature:** every edit you make in the UI is saved to `output/overrides.json`. Next run, your overrides come back pre-loaded. The tool remembers your skips, your manual values, your notes. Over time it reflects how *you* manage the account, not just what the math suggests.

**Nothing changes in Amazon without your explicit approval.** The browser review step is mandatory by design.

---

## Using with an AI agent (Claude, OpenClaw, etc.)

This tool is designed for human-in-the-loop operation — the browser review step is intentional, not something to skip. That said, it works well with an AI agent handling the data pipeline while you stay in control of the apply decision.

### How an agent uses this skill

An agent that can read `SKILL.md` (e.g. an OpenClaw agent or Claude Code) will:

1. Run `python run.py start --dry-run --ad-type both --days 30`
   — computes recommendations and writes `output/recs-<date>.json` without opening a browser or applying anything
2. Read the JSON output and format a summary of proposed changes
3. Present the diff to you in chat: which campaigns, which placements, current vs. recommended modifiers
4. Wait for your approval — either "apply all", "apply safe ones only", or "open browser review"
5. If approved directly: call `python run.py start` (without `--dry-run`) to launch the browser for your final click

**Why the apply step stays with you:** agents can misread context, data can be stale, and placement modifier changes affect real spend immediately. The browser review is a one-minute safeguard that keeps you in control.

### Agentic workflow example (OpenClaw / Claude Code)

If you have an OpenClaw agent configured with this skill:

```
User: "Run placement optimizer for the last 30 days, SP only, dry run first"

Agent: runs `python run.py start --days 30 --ad-type sp --dry-run`
       reads output/recs-*.json
       responds: "14 adjustments recommended across 6 campaigns.
                  Top of Search: avg −4pp (currently over ACOS target)
                  Product Page:  avg +6pp (under target, room to push)
                  3 flagged rows (modifier ≥ 300%) — recommend reviewing manually.
                  Ready to open browser for final review?"

User: "yes"

Agent: runs `python run.py start --days 30 --ad-type sp --no-browser`
       tells user: "Review ready at http://localhost:8501"
```

### Configuring for agent use

The `SKILL.md` file in this repo is written for AI agent consumption — it describes the CLI, the config format, the output schema, and the expected workflow. Drop the skill folder into your agent's workspace and point it at `SKILL.md`.

For OpenClaw specifically: install the skill via `npx clawhub@latest install amazon-placement-optimizer` (once published), then direct your agent to run `python run.py` from the skill directory.

---

## The feedback loop: how it learns

Every recommendation is reviewable before apply. In the **New Mod% column, every value is editable** — type your own number if you disagree with the suggestion. Add a note explaining why. Skip rows you want to leave alone. Hit Save.

Those decisions are written to `output/overrides.json`. The **next time you run**, your overrides come back pre-loaded. Your skips stay skipped. Your notes are still visible. Your manual modifier values are pre-filled.

Over weeks of use, the review page becomes a record of your strategy for that account — which placements you're aggressive on, which campaigns you never touch, which moves need a human sanity check.

**This is the workflow:**
1. Run → review → override where needed → save → apply
2. Next week: run again → previous notes and overrides are already loaded
3. The algorithm handles the math; you handle the strategy

---

## How the formula works

For each campaign × placement combination:

1. **Compute the gap** — how far is current ACOS from the midpoint of your target range?
2. **Apply dampening** — scale the move to avoid overcorrecting (default: 50% of the raw signal)
3. **Clamp to limits** — modifiers stay within `min_modifier_pct` and `max_modifier_pct`
4. **Zero-out rule** — if ACOS is far above target and modifier is already low, set to 0%
5. **Skip low-data** — placements with fewer than `min_clicks` clicks get no recommendation

### Worked example

| | Value |
|---|---|
| Target ACOS | 25–30% (midpoint 27.5%) |
| Current Top of Search ACOS | 38% |
| Current modifier | +60% |
| Dampening | 50% |

Gap = 38% − 27.5% = 10.5pp over target  
Adjustment = −10.5pp × 0.5 = −5.25pp  
**New modifier = 55%** — one controlled step in the right direction

---

## Prerequisites

- **Python 3.9+** — [download here](https://www.python.org/downloads/)
- **Amazon Ads API credentials** — [advertising.amazon.com/API/access](https://advertising.amazon.com/API/access)
  - Create an application → note **Client ID** and **Client Secret**
  - Needs at least one SP or SB profile

---

## Quick Start

```bash
# 1. Install dependencies (one-time)
pip install -r requirements.txt

# 2. Add your API credentials
cp .env.example .env
# Edit .env — set ADS_CLIENT_ID and ADS_CLIENT_SECRET

# 3. Authenticate
python run.py auth

# 4. Find your profile ID
python run.py list-profiles

# 5. Configure your account
cp config/account.yaml.example config/account.yaml
# Edit config/account.yaml — set profile_id and ACOS targets

# 6. Run
python run.py start --days 30
```

---

## The Review UI

Browser opens at `http://localhost:8501` after each run.

| Column | What it is |
|---|---|
| ✕ | Skip — checked rows are excluded from apply |
| Campaign | Campaign name |
| Placement | Top of Search, Product Page, Rest of Search, etc. |
| Type | SP or SB |
| Seg | NB (non-branded) or Brand |
| Spend / Sales / Clicks | Performance data for the date range |
| ACOS% | Current ACOS — red if above target, green if below |
| Target | Your ACOS target range from config |
| Cur Mod% | Current modifier on Amazon |
| **New Mod% ✏** | **Recommended modifier — editable** |
| Note | Free-text field for your reasoning |

**Two-step flow:**
1. **Save Edits** — writes overrides to `output/overrides.json`
2. **Apply to Amazon** — pushes non-skipped rows to the Ads API

---

## CLI Reference

| Command | What it does |
|---|---|
| `python run.py auth` | OAuth flow — saves refresh token to `.env` |
| `python run.py list-profiles` | List accessible profile IDs and names |
| `python run.py start` | Run the optimizer, open review UI |
| `python run.py status` | Check if a run is in progress |

### `start` options

| Flag | Default | Description |
|---|---|---|
| `--days 30` | 30 | Lookback window |
| `--start-date / --end-date` | — | Explicit date range |
| `--ad-type sp\|sb\|both` | `both` | Campaign types |
| `--dry-run` | off | Compute only — no browser, no apply |
| `--no-browser` | off | Don't auto-open browser |
| `--show-skipped` | off | Show low-data rows in terminal |

---

## Configuration (`config/account.yaml`)

```yaml
name: "My Account"
profile_id: "YOUR_PROFILE_ID"      # from list-profiles

nb_acos_low:   0.25    # 25% — min acceptable ACOS for non-branded
nb_acos_high:  0.35    # 35% — max acceptable ACOS for non-branded
brand_acos_low:  0.10
brand_acos_high: 0.20

min_modifier_pct: -90
max_modifier_pct: 900
max_increase_pp:  20   # max modifier increase per run

min_clicks:  10        # skip placements with fewer clicks
dampening:   0.5       # 0.5 = move 50% toward target per run
brand_dampening: 0.65

flag_threshold_pct: 300  # highlight rows where modifier ≥ 300%

brand_patterns:           # campaign name substrings = branded
  - "brand"
  - "branded"
  # add your brand name here
```

---

## Overrides file (`output/overrides.json`)

```json
{
  "CAMPAIGN_ID|TOP_OF_SEARCH": {
    "modifier_pct": 45,
    "skip": false,
    "note": "keep low — strong competitor here"
  },
  "CAMPAIGN_ID|PRODUCT_PAGE": {
    "modifier_pct": 0,
    "skip": true,
    "note": "exclude until Q3 review"
  }
}
```

Auto-loaded every time the review UI opens. Updated when you click Save Edits. Safe to commit to version control — it's your strategy record for the account.

---

## FAQ

**Q: Do I need to be a developer?**  
No. Terminal + text editor. Setup is one-time; after that it's `python run.py start`.

**Q: Will it apply changes automatically?**  
No. The browser review step is mandatory. `--dry-run` is available for zero-risk exploration.

**Q: What's a flagged row?**  
Any modifier above `flag_threshold_pct` (default 300%) gets a ⚠ and amber highlight. High modifiers spike spend fast — these are surfaced for intentional review, not auto-excluded.

**Q: How often should I run it?**  
Weekly for most accounts. Daily for high-spend. Dampening prevents overcorrection between runs.

**Q: If I always override a campaign the same way, do I have to redo it every run?**  
No. Save once → it's remembered. Your skip stays skipped, your manual value stays pre-filled, your note stays visible.

**Q: Multiple accounts?**  
Maintain separate `config/account.yaml` and `output/` per account. Multi-account support (via `--config` flag) is planned.

**Q: SP and SB both?**  
Yes — `--ad-type both` (default) runs both in parallel.

**Q: Is data sent anywhere?**  
No. Runs locally, talks directly to Amazon's API with your credentials.

---

## File structure

```
.
├── run.py                      # CLI entry point
├── SKILL.md                    # AI agent instructions (read this if using with an agent)
├── requirements.txt
├── .env.example                # Credential template
├── config/
│   └── account.yaml.example   # Account config template
├── lib/
│   ├── ads_api.py              # Amazon Ads API client
│   ├── optimizer.py            # Formula + recommendation builder
│   ├── worker.py               # Pipeline orchestration
│   ├── server.py               # Local review server
│   └── html_report.py          # Editable diff UI renderer
└── output/
    ├── overrides.json          # Your saved edits and notes
    └── recs-*.json             # Run outputs
```

---

## License

[MIT-0](https://opensource.org/licenses/MIT-0) — do whatever you want with it.
