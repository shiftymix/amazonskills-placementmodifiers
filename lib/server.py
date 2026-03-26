"""
Local review server for placement optimizer.
Serves the editable HTML report, persists overrides, and applies changes to Amazon.

Endpoints:
  GET  /          → interactive review page
  GET  /status    → JSON {status, message}
  POST /api/save  → persist overrides JSON
  GET  /api/overrides → load saved overrides
  POST /apply     → apply selected campaign IDs (JSON body: {campaign_ids, include_flagged})
  GET  /applied   → result page
"""

import json
import threading
import webbrowser
from pathlib import Path
from typing import Callable, Optional
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

from .optimizer import AccountConfig, Recommendation


class ReviewServer:
    """Wraps a simple HTTP server to serve the review UI."""

    def __init__(
        self,
        state,                          # WorkerState
        apply_fn: Callable,             # fn(recs) → list[dict]
        config: AccountConfig,
        port: int = 8501,
        output_dir: Path = Path("output"),
    ):
        self.state      = state
        self.apply_fn   = apply_fn
        self.config     = config
        self.port       = port
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._apply_results: list[dict] = []
        self._overrides_file = self.output_dir / "overrides.json"

    def _load_overrides(self) -> dict:
        """Return saved overrides {campaign_id|placement: {modifier_pct, skip, note}}."""
        if self._overrides_file.exists():
            try:
                return json.loads(self._overrides_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_overrides(self, data: dict):
        self._overrides_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _make_handler(self):
        server_self = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass  # silence access log

            def _send(self, code: int, body: str, content_type: str = "text/html; charset=utf-8"):
                b = body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def _send_json(self, code: int, data):
                self._send(code, json.dumps(data), "application/json")

            def _read_body(self) -> dict:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    return json.loads(raw)
                except Exception:
                    return {}

            def do_GET(self):
                path = urlparse(self.path).path

                if path == "/status":
                    self._send_json(200, {
                        "status": server_self.state.status,
                        "message": server_self.state.message,
                    })

                elif path == "/api/overrides":
                    self._send_json(200, server_self._load_overrides())

                elif path == "/applied":
                    from .html_report import render_applied_page
                    self._send(200, render_applied_page(server_self._apply_results))

                elif path == "/" or path == "":
                    state = server_self.state
                    if state.status in ("idle", "running"):
                        self._send(200, _loading_page(state.message))
                    elif state.status == "error":
                        self._send(500, f"<h2>Error: {state.error}</h2>")
                    else:
                        from .html_report import render_review_page
                        overrides = server_self._load_overrides()
                        html = render_review_page(
                            state.recommendations,
                            server_self.config,
                            overrides=overrides,
                        )
                        self._send(200, html)
                else:
                    self._send(404, "<h2>Not found</h2>")

            def do_POST(self):
                path = urlparse(self.path).path
                body = self._read_body()

                if path == "/api/save":
                    # Persist overrides: {key: {modifier_pct, skip, note}}
                    overrides = body.get("overrides", {})
                    server_self._save_overrides(overrides)
                    total    = len(overrides)
                    skipped  = sum(1 for v in overrides.values() if v.get("skip"))
                    noted    = sum(1 for v in overrides.values() if v.get("note"))
                    self._send_json(200, {
                        "ok": True,
                        "total": total,
                        "skipped": skipped,
                        "noted": noted,
                    })

                elif path == "/apply":
                    campaign_ids    = body.get("campaign_ids", [])
                    include_flagged = body.get("include_flagged", False)

                    recs = server_self.state.recommendations
                    # Filter to selected campaigns, respecting flagged gate
                    to_apply = [
                        r for r in recs
                        if not r.skip
                        and r.delta_pp != 0.0
                        and r.campaign_id in campaign_ids
                        and (include_flagged or not r.flagged)
                    ]

                    # Merge any manual modifier overrides from saved overrides file
                    overrides = server_self._load_overrides()
                    for r in to_apply:
                        key = f"{r.campaign_id}|{r.placement}"
                        if key in overrides:
                            ov = overrides[key]
                            if ov.get("skip"):
                                r.skip = True
                                continue
                            if ov.get("modifier_pct") is not None:
                                r.new_modifier = float(ov["modifier_pct"])

                    to_apply = [r for r in to_apply if not r.skip]

                    results = server_self.apply_fn(to_apply)
                    server_self._apply_results = results

                    self._send_json(200, {"redirect": "/applied"})

                else:
                    self._send(404, "<h2>Not found</h2>")

        return Handler

    def start(self, open_browser: bool = True):
        self._server = HTTPServer(("localhost", self.port), self._make_handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        print(f"\nReview UI: http://localhost:{self.port}")
        if open_browser:
            threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{self.port}")).start()

    def stop(self):
        if self._server:
            self._server.shutdown()


def _loading_page(message: str) -> str:
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="3">
<title>Loading…</title>
<style>body{{font-family:-apple-system,sans-serif;background:#0f1117;color:#e2e8f0;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0;}}
.box{{text-align:center;}}.spinner{{font-size:2em;animation:spin 1s linear infinite;}}
@keyframes spin{{from{{transform:rotate(0deg)}}to{{transform:rotate(360deg)}}}}</style>
</head><body><div class="box">
<div class="spinner">⟳</div>
<p style="margin-top:16px;color:#94a3b8">{message or 'Fetching placement data…'}</p>
<p style="color:#475569;font-size:0.85em">Page will refresh automatically.</p>
</div></body></html>"""
