"""
Local web server — serves the diff review UI and handles apply actions.
Runs on http://localhost:8501
"""

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from .html_report import render_review_page, render_applied_page
from .optimizer import Recommendation
from .worker import WorkerState


class _Handler(BaseHTTPRequestHandler):

    def log_message(self, *args):
        pass  # suppress request logging

    def do_GET(self):
        path = urlparse(self.path).path
        state: WorkerState = self.server.state

        if path in ("/", "/review"):
            if state.status == "running":
                self._html(f"<h2>Loading... {state.message}</h2><meta http-equiv='refresh' content='5'>")
            elif state.status == "ready":
                html = render_review_page(state.recommendations, state.config)
                self._html(html)
            elif state.status == "error":
                self._html(f"<h2>Error</h2><pre>{state.error}</pre>")
            else:
                self._html("<h2>Starting up...</h2><meta http-equiv='refresh' content='3'>")

        elif path == "/status":
            self._json({"status": state.status, "message": state.message})

        elif path == "/applied":
            html = render_applied_page(state.apply_results or [])
            self._html(html)

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path
        state: WorkerState = self.server.state

        if path == "/apply":
            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length)
            try:
                data = json.loads(body)
                selected_ids = set(data.get("campaign_ids", []))
                include_flagged = data.get("include_flagged", False)
            except Exception:
                self._json({"error": "bad request"}, 400)
                return

            to_apply = [
                r for r in state.recommendations
                if not r.skip
                and r.delta_pp != 0.0
                and r.campaign_id in selected_ids
                and (not r.flagged or include_flagged)
            ]

            results = self.server.apply_fn(to_apply)
            state.apply_results = results
            state.set("done", f"Applied {len(results)} changes")
            self._json({"applied": len(results), "redirect": "/applied"})

        else:
            self.send_response(404)
            self.end_headers()

    def _html(self, content: str, status: int = 200):
        body = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)


class ReviewServer:
    def __init__(self, state: WorkerState, apply_fn, config, port: int = 8501):
        self.port = port
        self._server = HTTPServer(("localhost", port), _Handler)
        self._server.state   = state
        self._server.apply_fn = apply_fn
        self._server.config  = config
        state.config = config
        self._thread: Optional[threading.Thread] = None

    def start(self, open_browser: bool = True):
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        url = f"http://localhost:{self.port}"
        print(f"\n  Review UI ready: {url}\n  Press Ctrl+C to exit after reviewing.\n")
        if open_browser:
            webbrowser.open(url)

    def stop(self):
        self._server.shutdown()
