"""
Amazon Ads API client for the placement optimizer.

Handles:
  - LWA OAuth (token refresh + auth code flow)
  - v1 unified campaign management (SP + SB) — GET modifiers, PUT modifiers
  - v3 Reporting API — placement performance report, poll, download
"""

import gzip
import json
import os
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from dotenv import load_dotenv, set_key

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOKEN_URL   = "https://api.amazon.com/auth/o2/token"
AUTH_URL    = "https://www.amazon.com/ap/oa"
ADS_BASE    = "https://advertising-api.amazon.com"
REPORT_BASE = f"{ADS_BASE}/reporting/reports"

OAUTH_SCOPE     = "advertising::campaign_management"
OAUTH_REDIRECT  = "http://localhost:8080"

# ---------------------------------------------------------------------------
# Placement label maps
# ---------------------------------------------------------------------------

PLACEMENT_NAMES = {
    "TOP_OF_SEARCH":        "Top of Search",
    "PRODUCT_PAGE":         "Product Page",
    "REST_OF_SEARCH":       "Rest of Search",
    "HOME_PAGE":            "Home Page",
    "SITE_AMAZON_BUSINESS": "Amazon Business",
}

# Report placementClassification string → v1 placement key
REPORT_PLACEMENT_MAP = {
    "Top of Search on-Amazon":   "TOP_OF_SEARCH",
    "Detail Page on-Amazon":     "PRODUCT_PAGE",
    "Other on-Amazon":           "REST_OF_SEARCH",
    "Home page on-Amazon":       "HOME_PAGE",
    "Homepage on-Amazon":        "HOME_PAGE",
    "Amazon Business on-Amazon": "SITE_AMAZON_BUSINESS",
    # Legacy variants
    "Top of search (on-site)":   "TOP_OF_SEARCH",
    "Detail Page on-site":       "PRODUCT_PAGE",
    "Other on-site":             "REST_OF_SEARCH",
    "Product pages on Amazon":   "PRODUCT_PAGE",
    "Rest of search":            "REST_OF_SEARCH",
}

SP_PLACEMENTS = ["TOP_OF_SEARCH", "PRODUCT_PAGE", "REST_OF_SEARCH"]
SB_PLACEMENTS = ["TOP_OF_SEARCH", "PRODUCT_PAGE", "REST_OF_SEARCH", "HOME_PAGE", "SITE_AMAZON_BUSINESS"]


# ---------------------------------------------------------------------------
# OAuth helpers
# ---------------------------------------------------------------------------

def run_oauth_flow(client_id: str, client_secret: str, env_file: Path) -> str:
    """
    Opens Amazon OAuth in the browser, captures the redirect, exchanges for
    tokens, writes ADS_REFRESH_TOKEN to env_file. Returns the refresh token.
    """
    state = os.urandom(8).hex()
    params = {
        "client_id":     client_id,
        "scope":         OAUTH_SCOPE,
        "response_type": "code",
        "redirect_uri":  OAUTH_REDIRECT,
        "state":         state,
    }
    auth_url = f"{AUTH_URL}?{urlencode(params)}"
    print(f"\nOpening browser for Amazon OAuth...\n{auth_url}\n")
    webbrowser.open(auth_url)

    # Spin up a local HTTP server to catch the redirect
    captured = {}

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            qs = parse_qs(urlparse(self.path).query)
            captured["code"]  = qs.get("code", [None])[0]
            captured["state"] = qs.get("state", [None])[0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<html><body><h2>Authorization complete. You can close this window.</h2></body></html>")

    server = HTTPServer(("localhost", 8080), _Handler)
    print("Waiting for Amazon to redirect back to localhost:8080 ...")
    server.handle_request()

    code = captured.get("code")
    if not code:
        raise RuntimeError("No auth code received from Amazon redirect.")

    resp = requests.post(TOKEN_URL, data={
        "grant_type":   "authorization_code",
        "code":         code,
        "redirect_uri": OAUTH_REDIRECT,
        "client_id":    client_id,
        "client_secret": client_secret,
    })
    resp.raise_for_status()
    tokens = resp.json()
    refresh_token = tokens["refresh_token"]

    set_key(str(env_file), "ADS_REFRESH_TOKEN", refresh_token)
    print(f"\n✓ Refresh token written to {env_file}")
    return refresh_token


def get_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    resp = requests.post(TOKEN_URL, data={
        "grant_type":    "refresh_token",
        "refresh_token": refresh_token,
        "client_id":     client_id,
        "client_secret": client_secret,
    })
    resp.raise_for_status()
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# AdsClient
# ---------------------------------------------------------------------------

class AdsClient:
    """
    Generic Amazon Ads API client. Initialized with a profile_id (Advertising
    profile) and LWA credentials. Handles token refresh and rate limiting.
    """

    def __init__(self, profile_id: str, client_id: str, client_secret: str, refresh_token: str):
        self.profile_id    = str(profile_id)
        self.client_id     = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self._token: Optional[str] = None
        self._last_request: float = 0.0
        self._min_interval: float = 1.0   # seconds between requests

    def _throttle(self):
        elapsed = time.time() - self._last_request
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request = time.time()

    def _ensure_token(self):
        if not self._token:
            self._token = get_access_token(self.client_id, self.client_secret, self.refresh_token)

    def _auth_headers(self, extra: dict = None) -> dict:
        self._ensure_token()
        h = {
            "Authorization":                   f"Bearer {self._token}",
            "Amazon-Advertising-API-ClientId": self.client_id,
            "Amazon-Advertising-API-Scope":    self.profile_id,
            "Content-Type":                    "application/json",
        }
        if extra:
            h.update(extra)
        return h

    def _post(self, path: str, body: dict, extra_headers: dict = None, retries: int = 3) -> dict:
        for attempt in range(retries):
            self._throttle()
            resp = requests.post(
                f"{ADS_BASE}{path}",
                headers=self._auth_headers(extra_headers),
                json=body,
                timeout=30,
            )
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 10 * (attempt + 1)))
                print(f"  Rate limited — waiting {retry_after}s ...")
                time.sleep(retry_after)
                self._token = None  # force token refresh
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError(f"POST {path} failed after {retries} attempts (rate limited)")

    # -----------------------------------------------------------------------
    # Profile discovery
    # -----------------------------------------------------------------------

    def list_profiles(self) -> list[dict]:
        """Return all advertising profiles accessible to this LWA token."""
        self._ensure_token()
        self._throttle()
        resp = requests.get(
            f"{ADS_BASE}/v2/profiles",
            headers={
                "Authorization":                   f"Bearer {self._token}",
                "Amazon-Advertising-API-ClientId": self.client_id,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    # -----------------------------------------------------------------------
    # v1 Campaign Management — read
    # -----------------------------------------------------------------------

    def get_campaigns(
        self,
        ad_product: str = "SPONSORED_PRODUCTS",
        states: list = None,
    ) -> list[dict]:
        """
        Return campaigns with placement bid adjustments via v1 unified API.

        ad_product: "SPONSORED_PRODUCTS" | "SPONSORED_BRANDS" | "SPONSORED_DISPLAY"
        states: default ["ENABLED", "PAUSED"]

        Each campaign includes:
          campaignId, name, adProduct, state,
          optimizations.bidSettings.bidAdjustments.placementBidAdjustments
        """
        if states is None:
            states = ["ENABLED", "PAUSED"]

        max_results = 1000 if ad_product == "SPONSORED_PRODUCTS" else 100
        campaigns, next_token = [], None

        while True:
            body = {
                "adProductFilter": {"include": [ad_product]},
                "stateFilter":     {"include": states},
                "maxResults":      max_results,
            }
            if next_token:
                body["nextToken"] = next_token

            data = self._post("/adsApi/v1/query/campaigns", body)
            campaigns.extend(data.get("campaigns", []))
            next_token = data.get("nextToken")
            if not next_token:
                break

        return campaigns

    # -----------------------------------------------------------------------
    # v1 Campaign Management — write
    # -----------------------------------------------------------------------

    def update_campaigns(self, updates: list[dict]) -> dict:
        """
        Update placement modifiers via v1 unified API.

        Each update:
          {
            "campaignId": "...",
            "adProduct": "SPONSORED_PRODUCTS",
            "optimizations": {
              "bidSettings": {
                "bidAdjustments": {
                  "placementBidAdjustments": [
                    {"placement": "TOP_OF_SEARCH", "percentage": 30}
                  ]
                }
              }
            }
          }

        Returns {"success": [...], "error": [...]}
        HTTP 207 is normal for batch updates.
        """
        resp = requests.post(
            f"{ADS_BASE}/adsApi/v1/update/campaigns",
            headers=self._auth_headers(),
            json={"campaigns": updates},
            timeout=30,
        )
        if resp.status_code not in (200, 207):
            resp.raise_for_status()
        return resp.json()

    # -----------------------------------------------------------------------
    # v3 Reporting API
    # -----------------------------------------------------------------------

    def request_sp_placement_report(self, start_date: str, end_date: str) -> str:
        """
        Request a v3 SP Campaigns placement report.
        start_date / end_date: "YYYY-MM-DD". Returns report ID.

        IMPORTANT: groupBy must be ["campaignPlacement"] ONLY.
        placementClassification MUST be listed explicitly in columns.
        """
        headers = self._auth_headers({
            "Content-Type": "application/vnd.createasyncreportrequest.v3+json",
        })
        body = {
            "name":      f"SP Placement {start_date} to {end_date}",
            "startDate": start_date,
            "endDate":   end_date,
            "configuration": {
                "adProduct":    "SPONSORED_PRODUCTS",
                "groupBy":      ["campaignPlacement"],
                "columns": [
                    "campaignId",
                    "campaignName",
                    "placementClassification",
                    "impressions",
                    "clicks",
                    "cost",
                    "purchases30d",
                    "sales30d",
                ],
                "reportTypeId": "spCampaigns",
                "timeUnit":     "SUMMARY",
                "format":       "GZIP_JSON",
            },
        }
        resp = requests.post(REPORT_BASE, headers=headers, json=body, timeout=30)
        if not resp.ok:
            raise RuntimeError(f"SP report request failed ({resp.status_code}): {resp.text}")
        return resp.json()["reportId"]

    def request_sb_placement_report(self, start_date: str, end_date: str) -> str:
        """
        Request a v3 SB Campaign Placement report.
        Note: uses 'sales' (not 'sales30d'), 'purchases' (not 'purchases30d').
        reportTypeId: "sbCampaignPlacement"
        """
        headers = self._auth_headers({
            "Content-Type": "application/vnd.createasyncreportrequest.v3+json",
        })
        body = {
            "name":      f"SB Placement {start_date} to {end_date}",
            "startDate": start_date,
            "endDate":   end_date,
            "configuration": {
                "adProduct":    "SPONSORED_BRANDS",
                "groupBy":      ["campaignPlacement"],
                "columns": [
                    "campaignId",
                    "campaignName",
                    "placementClassification",
                    "impressions",
                    "clicks",
                    "cost",
                    "purchases",
                    "sales",
                ],
                "reportTypeId": "sbCampaignPlacement",
                "timeUnit":     "SUMMARY",
                "format":       "GZIP_JSON",
            },
        }
        resp = requests.post(REPORT_BASE, headers=headers, json=body, timeout=30)
        if not resp.ok:
            raise RuntimeError(f"SB report request failed ({resp.status_code}): {resp.text}")
        return resp.json()["reportId"]

    def poll_report(self, report_id: str, max_wait: int = 7200) -> dict:
        """
        Poll until report is COMPLETED. Returns the completed report object.
        Uses exponential backoff: 30s → 60s → 120s (cap). Max wait: 2 hours.
        """
        intervals = [30, 60, 120]
        elapsed, idx = 0, 0

        while elapsed < max_wait:
            wait = intervals[min(idx, len(intervals) - 1)]
            print(f"  Polling report {report_id[:16]}... (elapsed {elapsed}s, next check in {wait}s)")
            time.sleep(wait)
            elapsed += wait
            idx += 1

            try:
                self._throttle()
                resp = requests.get(
                    f"{REPORT_BASE}/{report_id}",
                    headers=self._auth_headers(),
                    timeout=30,
                )
                resp.raise_for_status()
            except requests.RequestException as e:
                print(f"  Poll error (will retry): {e}")
                continue

            data   = resp.json()
            status = data.get("status", "UNKNOWN")

            if status == "COMPLETED":
                print(f"  Report COMPLETED (elapsed {elapsed}s)")
                return data
            if status == "FAILED":
                raise RuntimeError(f"Report FAILED: {data.get('failureReason', data)}")

        raise TimeoutError(
            f"Report {report_id} still PENDING after {max_wait}s. "
            f"Re-run with --report-id {report_id} to resume."
        )

    def download_report(self, url: str) -> list[dict]:
        """Download and decompress a GZIP_JSON report. Returns list of row dicts."""
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        return json.loads(gzip.decompress(resp.content))


# ---------------------------------------------------------------------------
# Factory: build client from .env
# ---------------------------------------------------------------------------

def client_from_env(env_file: Path, profile_id: str) -> AdsClient:
    """
    Load credentials from .env and return an AdsClient for the given profile.
    Raises a clear EnvironmentError if any credential is missing.
    """
    load_dotenv(env_file)

    client_id     = os.getenv("ADS_CLIENT_ID", "").strip()
    client_secret = os.getenv("ADS_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("ADS_REFRESH_TOKEN", "").strip()

    missing = [k for k, v in {
        "ADS_CLIENT_ID":     client_id,
        "ADS_CLIENT_SECRET": client_secret,
        "ADS_REFRESH_TOKEN": refresh_token,
    }.items() if not v]

    if missing:
        raise EnvironmentError(
            f"Missing credentials in .env: {', '.join(missing)}\n"
            f"  Run: python run.py auth\n"
            f"  Or copy .env.example to .env and fill in your credentials."
        )

    return AdsClient(profile_id, client_id, client_secret, refresh_token)
