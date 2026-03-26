# Setup Guide — Amazon Placement Optimizer

This skill uses the Amazon Advertising API. Here's how to get from zero to running in 4 steps.

---

## Step 1 — Get Amazon Ads API Access

You need an Amazon Ads developer application (LWA app) to get credentials.

**If you manage your own brand:**
1. Go to https://advertising.amazon.com/API/access
2. Sign in with the Amazon account that owns your Advertising account
3. Click **Request Access** → fill out the form (select "Self-serve tool" as use case)
4. You'll receive `CLIENT_ID` and `CLIENT_SECRET` within a few days

**If you're an agency managing client accounts:**
- Apply at the same URL, select "Agency tool" as use case
- Your LWA app will be granted access to profiles across all managed accounts

> ⚠️ Amazon Ads API access requires approval. Allow 2–5 business days.
> During this time you can complete Steps 2–3 and be ready to run immediately on approval.

---

## Step 2 — Install Python dependencies

```bash
pip install -r requirements.txt
```

Or with `uv` (recommended — faster):
```bash
uv pip install -r requirements.txt
```

Requires Python 3.10+.

---

## Step 3 — Set up credentials

Copy the example env file:
```bash
cp .env.example .env
```

Open `.env` and fill in your client credentials:
```
ADS_CLIENT_ID=amzn1.application-oa2-client.xxxxx
ADS_CLIENT_SECRET=your-client-secret-here
ADS_REFRESH_TOKEN=    ← leave blank for now, run auth next
```

Then run the OAuth flow to get your refresh token:
```bash
python run.py auth
```

This opens a browser window → you log in with your Amazon Ads account → the refresh token is written automatically to `.env`.

> You only need to run `auth` once. The refresh token is long-lived.

---

## Step 4 — Find your profile ID and configure

List the advertising profiles your credentials can access:
```bash
python run.py list-profiles
```

Output looks like:
```
Profile ID          Account Name                  Type        Marketplace
1234567890123456    My Brand (Sponsored Ads)      seller      US
9876543210987654    My Agency Client              vendor      US
```

Copy the profile ID for the account you want to optimize.

Now set up your account config:
```bash
cp config/account.yaml.example config/account.yaml
```

Edit `config/account.yaml`:
```yaml
profile_id: "1234567890123456"     # ← paste your profile ID here
name: "My Brand"                   # ← human label, just for display

# ACOS targets (as decimals: 0.25 = 25%)
# Use a range — modifiers within range are left alone.
# The optimizer calculates toward the midpoint of the range.
nb_acos_low:    0.20   # nonbrand lower bound
nb_acos_high:   0.28   # nonbrand upper bound

brand_acos_low:  0.10  # brand lower bound
brand_acos_high: 0.15  # brand upper bound

# Brand detection — campaign name patterns (case-insensitive)
# Campaigns matching any pattern use the brand ACOS targets.
brand_patterns:
  - "Branded"
  - "Brand"

# Adjustment rules
min_clicks: 20           # skip placement if fewer clicks than this
max_increase_pp: 20      # max percentage-point increase per run
dampening: 0.50          # 0.50 = move 50% of full calculated delta per run
flag_threshold_pct: 50   # modifiers >= this need --include-flagged to apply
```

---

## Step 5 — Run it

```bash
python run.py start --days 30
```

The tool will:
1. Request placement performance reports (can take 5–45 min for large accounts)
2. Show you a diff table in your browser at http://localhost:8501
3. Wait for your approval before applying any changes

For a dry run (no changes, just see recommendations):
```bash
python run.py start --days 30 --dry-run
```

---

## Troubleshooting

**`Missing in .env: ADS_CLIENT_ID`**
→ `.env` file doesn't exist or credentials aren't filled in. Run `cp .env.example .env` and add your credentials.

**`Unknown account` or profile not found**
→ Your refresh token may not have access to that profile. Run `python run.py list-profiles` to see what's accessible.

**Report polling takes a long time**
→ Normal for accounts with many campaigns. Reports can take up to 45 minutes. The poll loop handles this automatically. If your process is interrupted, re-run with `--report-id <id>` (the ID is printed when the report is requested).

**`429 Too Many Requests`**
→ The client auto-retries with backoff. If it persists, wait a few minutes and try again.

**Modifiers flagged but not applying**
→ Some campaigns have modifiers above `flag_threshold_pct` (default 50%). These require `--include-flagged` to apply. Review them manually first.
