"""
Worker: orchestrates report requests, polling, data merge, and recommendation build.
Runs as a background thread or directly from run.py.
"""

import json
import threading
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Optional

import yaml

from .ads_api import AdsClient, REPORT_PLACEMENT_MAP, SP_PLACEMENTS, SB_PLACEMENTS
from .optimizer import AccountConfig, PlacementPerf, build_recommendations, Recommendation


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def load_account_config(config_path: Path) -> AccountConfig:
    """Load account.yaml into an AccountConfig."""
    if not config_path.exists():
        example = config_path.parent / "account.yaml.example"
        raise FileNotFoundError(
            f"Account config not found: {config_path}\n"
            f"  Copy {example} to {config_path} and fill in your values.\n"
            f"  Then run: python run.py list-profiles  (to find your profile_id)"
        )

    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    profile_id = raw.get("profile_id", "")
    if not profile_id or profile_id == "YOUR_PROFILE_ID_HERE":
        raise ValueError(
            "profile_id not set in config/account.yaml.\n"
            "  Run: python run.py list-profiles  to find your profile ID."
        )

    return AccountConfig(
        profile_id=str(profile_id),
        name=raw.get("name", "My Account"),
        nb_acos_low=float(raw.get("nb_acos_low", 0.20)),
        nb_acos_high=float(raw.get("nb_acos_high", 0.28)),
        brand_acos_low=float(raw.get("brand_acos_low", 0.10)),
        brand_acos_high=float(raw.get("brand_acos_high", 0.15)),
        brand_patterns=raw.get("brand_patterns", ["Branded", "Brand"]),
        min_clicks=int(raw.get("min_clicks", 20)),
        max_increase_pp=float(raw.get("max_increase_pp", 20.0)),
        dampening=float(raw.get("dampening", 0.50)),
        brand_dampening=float(raw.get("brand_dampening", 0.65)),
        dampening_high_modifier=float(raw.get("dampening_high_modifier", 0.80)),
        high_modifier_threshold=float(raw.get("high_modifier_threshold", 20.0)),
        zero_out_acos_threshold=float(raw.get("zero_out_acos_threshold", 0.50)),
        zero_out_max_modifier=float(raw.get("zero_out_max_modifier", 20.0)),
        flag_threshold_pct=float(raw.get("flag_threshold_pct", 50.0)),
    )


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def date_range_from_days(days: int) -> tuple[str, str]:
    end   = date.today() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Data merge: report rows + campaign modifiers → PlacementPerf list
# ---------------------------------------------------------------------------

def _current_modifiers(campaigns: list[dict], ad_type: str) -> dict[tuple, float]:
    """
    Returns {(campaign_id, placement_key): modifier_pct} from v1 campaign data.
    """
    result = {}
    for c in campaigns:
        cid = c.get("campaignId", "")
        adjustments = (
            c.get("optimizations", {})
             .get("bidSettings", {})
             .get("bidAdjustments", {})
             .get("placementBidAdjustments", [])
        ) or []
        # Build a map of placement → % for this campaign
        adj_map = {a["placement"]: a.get("percentage", 0) for a in adjustments}
        placements = SP_PLACEMENTS if ad_type == "SP" else SB_PLACEMENTS
        for p in placements:
            result[(cid, p)] = adj_map.get(p, 0.0)
    return result


def _parse_report_rows(rows: list[dict], ad_type: str) -> dict[tuple, dict]:
    """
    Returns {(campaign_id, placement_key): {clicks, spend, sales}} from report rows.
    Sales field differs: SP uses 'sales30d', SB uses 'sales'.
    """
    result = {}
    sales_field = "sales30d" if ad_type == "SP" else "sales"

    for row in rows:
        cid      = str(row.get("campaignId", ""))
        cname    = row.get("campaignName", "")
        place_raw = row.get("placementClassification", "")
        place_key = REPORT_PLACEMENT_MAP.get(place_raw)
        if not place_key:
            continue

        clicks = int(row.get("clicks", 0))
        spend  = float(row.get("cost", 0))
        sales  = float(row.get(sales_field, 0))

        key = (cid, place_key)
        if key not in result:
            result[key] = {"campaign_name": cname, "clicks": 0, "spend": 0.0, "sales": 0.0}
        result[key]["clicks"] += clicks
        result[key]["spend"]  += spend
        result[key]["sales"]  += sales

    return result


def merge_data(
    report_rows: list[dict],
    campaigns: list[dict],
    ad_type: str,
) -> list[PlacementPerf]:
    """Merge report performance + current modifiers into PlacementPerf list."""
    modifiers = _current_modifiers(campaigns, ad_type)
    perf_data = _parse_report_rows(report_rows, ad_type)

    results = []
    for (cid, placement), perf in perf_data.items():
        cname    = perf["campaign_name"]
        modifier = modifiers.get((cid, placement), 0.0)
        results.append(PlacementPerf(
            campaign_id=cid,
            campaign_name=cname,
            placement=placement,
            ad_type=ad_type,
            clicks=perf["clicks"],
            spend=perf["spend"],
            sales=perf["sales"],
            cur_modifier=modifier,
        ))

    return results


# ---------------------------------------------------------------------------
# Worker state
# ---------------------------------------------------------------------------

class WorkerState:
    """Shared state between worker thread and server."""

    def __init__(self):
        self.status: str = "idle"          # idle | running | ready | applying | done | error
        self.message: str = ""
        self.recommendations: list[Recommendation] = []
        self.report_ids: dict[str, str] = {}   # {"SP": id, "SB": id}
        self.error: Optional[str] = None
        self._lock = threading.Lock()

    def set(self, status: str, message: str = ""):
        with self._lock:
            self.status = status
            self.message = message

    def set_recs(self, recs: list[Recommendation]):
        with self._lock:
            self.recommendations = recs
            self.status = "ready"

    def set_error(self, err: str):
        with self._lock:
            self.error = err
            self.status = "error"


# ---------------------------------------------------------------------------
# Main worker function
# ---------------------------------------------------------------------------

def run_worker(
    client: AdsClient,
    config: AccountConfig,
    start_date: str,
    end_date: str,
    ad_type: str,           # "sp" | "sb" | "both"
    state: WorkerState,
    output_dir: Path,
    on_progress: Optional[Callable[[str], None]] = None,
):
    """
    Full pipeline: request reports → poll → download → merge → build recs.
    Writes state into `state` object. Called in a background thread.
    """
    def log(msg: str):
        print(f"  [worker] {msg}")
        state.set("running", msg)
        if on_progress:
            on_progress(msg)

    try:
        report_ids = {}
        ad_types_to_run = []
        if ad_type in ("sp", "both"):
            ad_types_to_run.append("SP")
        if ad_type in ("sb", "both"):
            ad_types_to_run.append("SB")

        # Request reports
        for at in ad_types_to_run:
            log(f"Requesting {at} placement report ({start_date} → {end_date})...")
            if at == "SP":
                rid = client.request_sp_placement_report(start_date, end_date)
            else:
                rid = client.request_sb_placement_report(start_date, end_date)
            report_ids[at] = rid
            log(f"  {at} report ID: {rid}")

        # Save report IDs in case of interruption
        state.report_ids = report_ids
        (output_dir / "report_ids.json").write_text(json.dumps(report_ids, indent=2))

        # Poll + download each report
        all_rows: dict[str, list[dict]] = {}
        for at, rid in report_ids.items():
            log(f"Polling {at} report {rid[:16]}...")
            completed = client.poll_report(rid)
            url = completed.get("url") or completed.get("downloadUrl") or completed.get("location")
            if not url:
                raise RuntimeError(f"No download URL in completed report: {completed}")
            log(f"  Downloading {at} report...")
            rows = client.download_report(url)
            all_rows[at] = rows
            log(f"  {at}: {len(rows)} rows")

        # Fetch current campaign modifiers
        all_placements: list[PlacementPerf] = []
        for at in ad_types_to_run:
            ad_product = "SPONSORED_PRODUCTS" if at == "SP" else "SPONSORED_BRANDS"
            log(f"Fetching {at} campaign modifiers...")
            campaigns = client.get_campaigns(ad_product=ad_product, states=["ENABLED"])
            log(f"  {at}: {len(campaigns)} enabled campaigns")
            merged = merge_data(all_rows[at], campaigns, at)
            all_placements.extend(merged)

        # Build recommendations
        log(f"Computing recommendations for {len(all_placements)} placement records...")
        recs = build_recommendations(all_placements, config)

        actionable = [r for r in recs if not r.skip and r.delta_pp != 0.0]
        log(f"Done. {len(actionable)} adjustments recommended.")

        # Save to output
        output_file = output_dir / f"recs-{start_date}-to-{end_date}.json"
        output_file.write_text(json.dumps(
            [r.__dict__ for r in recs], indent=2, default=str
        ))

        state.set_recs(recs)

    except Exception as e:
        state.set_error(str(e))
        raise
