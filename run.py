#!/usr/bin/env python3
"""
Amazon Placement Optimizer — CLI entry point.

Commands:
  auth                   Run OAuth flow to get a refresh token
  list-profiles          List accessible Amazon Ads profile IDs
  start                  Run the placement optimizer
  status                 Check status of a running job
"""

import argparse
import os
import sys
import threading
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT       = Path(__file__).parent
ENV_FILE   = ROOT / ".env"
CONFIG_DIR = ROOT / "config"
CONFIG_FILE = CONFIG_DIR / "account.yaml"
OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------

def cmd_auth(args):
    load_dotenv(ENV_FILE)
    client_id     = os.getenv("ADS_CLIENT_ID", "").strip()
    client_secret = os.getenv("ADS_CLIENT_SECRET", "").strip()

    if not client_id or "REPLACE_ME" in client_id:
        print("ERROR: ADS_CLIENT_ID not set in .env")
        print("  1. Get credentials at: https://advertising.amazon.com/API/access")
        print("  2. Copy .env.example to .env and fill in ADS_CLIENT_ID + ADS_CLIENT_SECRET")
        sys.exit(1)
    if not client_secret or "REPLACE_ME" in client_secret:
        print("ERROR: ADS_CLIENT_SECRET not set in .env")
        sys.exit(1)

    from lib.ads_api import run_oauth_flow
    try:
        token = run_oauth_flow(client_id, client_secret, ENV_FILE)
        print(f"\nAuthentication successful.")
        print(f"Run: python run.py list-profiles  to find your profile ID.")
    except Exception as e:
        print(f"ERROR: OAuth failed: {e}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# list-profiles
# ---------------------------------------------------------------------------

def cmd_list_profiles(args):
    load_dotenv(ENV_FILE)
    client_id     = os.getenv("ADS_CLIENT_ID", "").strip()
    client_secret = os.getenv("ADS_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("ADS_REFRESH_TOKEN", "").strip()

    if not all([client_id, client_secret, refresh_token]):
        print("ERROR: Credentials missing. Run: python run.py auth")
        sys.exit(1)

    from lib.ads_api import AdsClient
    client = AdsClient("0", client_id, client_secret, refresh_token)

    print("\nFetching accessible profiles...\n")
    try:
        profiles = client.list_profiles()
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    if not profiles:
        print("No profiles found. Check that your credentials have advertising access.")
        sys.exit(0)

    print(f"{'Profile ID':<22} {'Account Name':<45} {'Type':<10} {'Marketplace'}")
    print("-" * 90)
    for p in profiles:
        pid   = str(p.get("profileId", ""))
        name  = p.get("accountInfo", {}).get("name", "") or p.get("countryCode", "")
        atype = p.get("accountInfo", {}).get("type", "")
        mkt   = p.get("countryCode", "")
        print(f"{pid:<22} {name:<45} {atype:<10} {mkt}")

    print(f"\n{len(profiles)} profiles found.")
    print("\nNext: set profile_id in config/account.yaml")


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------

def cmd_start(args):
    from lib.ads_api import client_from_env
    from lib.worker import load_account_config, date_range_from_days, WorkerState, run_worker
    from lib.server import ReviewServer
    from lib.optimizer import format_diff_table

    # Load config
    try:
        config = load_account_config(CONFIG_FILE)
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    # Build client
    try:
        client = client_from_env(ENV_FILE, config.profile_id)
    except EnvironmentError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    # Date range
    if args.start_date and args.end_date:
        start_date, end_date = args.start_date, args.end_date
    else:
        days = args.days or 30
        start_date, end_date = date_range_from_days(days)

    print(f"\nAmazon Placement Optimizer")
    print(f"  Account:    {config.name} ({config.profile_id})")
    print(f"  Date range: {start_date} → {end_date}")
    print(f"  Ad types:   {args.ad_type.upper()}")
    print(f"  NB ACOS:    {config.nb_acos_low*100:.0f}%–{config.nb_acos_high*100:.0f}%  "
          f"(target {(config.nb_acos_low+config.nb_acos_high)/2*100:.0f}%)")
    print(f"  Brand ACOS: {config.brand_acos_low*100:.0f}%–{config.brand_acos_high*100:.0f}%  "
          f"(target {(config.brand_acos_low+config.brand_acos_high)/2*100:.0f}%)")
    print(f"  Min clicks: {config.min_clicks}")
    if args.dry_run:
        print(f"  Mode:       DRY RUN (no changes will be applied)")

    confirm = input("\nConfirm? [yes/no] ").strip().lower()
    if confirm not in ("y", "yes"):
        print("Aborted.")
        sys.exit(0)

    state = WorkerState()

    # Apply function
    def apply_fn(recs_to_apply):
        results = []
        # Group by campaign+ad_type
        from collections import defaultdict
        by_campaign = defaultdict(list)
        for r in recs_to_apply:
            by_campaign[(r.campaign_id, r.ad_type)].append(r)

        updates = []
        for (cid, at), camp_recs in by_campaign.items():
            ad_product = "SPONSORED_PRODUCTS" if at == "SP" else "SPONSORED_BRANDS"
            adjustments = [
                {"placement": r.placement, "percentage": round(r.new_modifier)}
                for r in camp_recs
            ]
            updates.append({
                "campaignId": cid,
                "adProduct":  ad_product,
                "optimizations": {
                    "bidSettings": {
                        "bidAdjustments": {
                            "placementBidAdjustments": adjustments
                        }
                    }
                }
            })

        if args.dry_run:
            print(f"\nDRY RUN — would apply {len(updates)} campaign updates")
            for u in updates:
                print(f"  {u['campaignId']}: {u['optimizations']['bidSettings']['bidAdjustments']['placementBidAdjustments']}")
            return [{"campaign_id": u["campaignId"], "status": "dry_run",
                     "placement": "", "old_modifier": "", "new_modifier": ""} for u in updates]

        # Batch in groups of 50
        BATCH = 50
        for i in range(0, len(updates), BATCH):
            batch = updates[i:i+BATCH]
            resp = client.update_campaigns(batch)
            for item in resp.get("success", []):
                results.append({
                    "campaign_id": item.get("campaignId", ""),
                    "campaign_name": "",
                    "placement": "",
                    "old_modifier": "",
                    "new_modifier": "",
                    "status": "ok",
                })
            for item in resp.get("error", []):
                results.append({
                    "campaign_id": item.get("campaignId", ""),
                    "campaign_name": "",
                    "placement": "",
                    "old_modifier": "",
                    "new_modifier": "",
                    "status": f"error: {item.get('message', 'unknown')}",
                })

        # Save result
        import json
        result_file = OUTPUT_DIR / f"applied-{date.today().isoformat()}.json"
        result_file.write_text(json.dumps(results, indent=2))
        print(f"\nResults saved to {result_file}")
        return results

    # Run worker in background thread
    t = threading.Thread(
        target=run_worker,
        args=(client, config, start_date, end_date, args.ad_type, state, OUTPUT_DIR),
        daemon=True,
    )
    t.start()

    # Start review server
    server = ReviewServer(state, apply_fn, config, port=8501)
    server.start(open_browser=not args.no_browser)

    try:
        t.join()
        if state.status == "error":
            print(f"\nERROR: {state.error}")
            sys.exit(1)

        if args.dry_run:
            # Print terminal diff and exit
            print(format_diff_table(state.recommendations, include_skipped=args.show_skipped))
            print("\nDry run complete. No changes applied.")
            sys.exit(0)

        print("\nReview the recommendations at http://localhost:8501")
        print("Press Ctrl+C when done.\n")

        import time
        while state.status not in ("done", "error"):
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nExiting.")
    finally:
        server.stop()

    if state.status == "done":
        print(f"\nDone. {state.message}")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def cmd_status(args):
    import requests
    try:
        r = requests.get("http://localhost:8501/status", timeout=3)
        data = r.json()
        print(f"Status: {data['status']}  —  {data.get('message', '')}")
    except Exception:
        print("No active run found (server not running on port 8501).")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Amazon Placement Optimizer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  auth                 Run OAuth flow to get a refresh token
  list-profiles        List accessible Amazon Ads profile IDs + names
  start                Run the optimizer
  status               Check if a run is in progress

Examples:
  python run.py auth
  python run.py list-profiles
  python run.py start --days 30
  python run.py start --days 30 --ad-type sp --dry-run
  python run.py start --start-date 2026-03-01 --end-date 2026-03-25
        """
    )
    sub = parser.add_subparsers(dest="cmd")

    # auth
    sub.add_parser("auth", help="OAuth flow — get refresh token")

    # list-profiles
    sub.add_parser("list-profiles", help="List accessible profile IDs")

    # start
    p_start = sub.add_parser("start", help="Run the optimizer")
    p_start.add_argument("--days",        type=int,   default=30,    help="Lookback days (default: 30)")
    p_start.add_argument("--start-date",  type=str,   default=None,  help="Explicit start date YYYY-MM-DD")
    p_start.add_argument("--end-date",    type=str,   default=None,  help="Explicit end date YYYY-MM-DD")
    p_start.add_argument("--ad-type",     type=str,   default="both", choices=["sp", "sb", "both"],
                          help="Campaign types to optimize (default: both)")
    p_start.add_argument("--dry-run",     action="store_true",        help="Compute only, do not apply")
    p_start.add_argument("--show-skipped", action="store_true",       help="Show skipped placements in terminal")
    p_start.add_argument("--include-flagged", action="store_true",    help="Apply flagged (high modifier) changes")
    p_start.add_argument("--no-browser",  action="store_true",        help="Don't auto-open browser")
    p_start.add_argument("--report-id",   type=str,   default=None,  help="Resume polling an existing report ID")

    # status
    sub.add_parser("status", help="Check status of a running job")

    args = parser.parse_args()

    if args.cmd == "auth":
        cmd_auth(args)
    elif args.cmd == "list-profiles":
        cmd_list_profiles(args)
    elif args.cmd == "start":
        cmd_start(args)
    elif args.cmd == "status":
        cmd_status(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
