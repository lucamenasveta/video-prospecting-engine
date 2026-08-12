"""
Local web UI for the Video Prospecting Engine.

A zero-dependency (standard-library only) web server that wraps
video_prospector.py so anyone can generate assets from a browser — no command
line. Run it and open the printed URL:

    python app.py            # http://localhost:8000
    python app.py 9000       # custom port

Mock mode works offline. Anthropic mode uses a Claude API key that you paste in
the UI; the key is used only to serve that one request and is never written to
disk or logged.
"""

import base64
import io
import json
import shutil
import sys
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import video_prospector as engine

ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"
OUT_DIR = ROOT / "output"


def _run_pipeline(payload):
    """Run the engine for one UI request and return a JSON-able result dict."""
    brand = (payload.get("brand") or "Your Studio").strip()
    provider = payload.get("provider") or "mock"
    model = (payload.get("model") or "claude-opus-5").strip()
    api_key = (payload.get("api_key") or "").strip() or None
    rows = payload.get("prospects") or []

    prospects = []
    for row in rows:
        company = (row.get("company") or "").strip()
        if not company:
            continue
        prospects.append(engine.Prospect(
            first_name=(row.get("first_name") or "").strip() or "there",
            company=company,
            role=(row.get("role") or "").strip(),
            industry=(row.get("industry") or "").strip(),
            website=(row.get("website") or "").strip(),
        ))
    if not prospects:
        return {"error": "Add at least one prospect with a company name."}

    # Fresh output each run so the gallery and zip reflect only this request.
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_assets, succeeded, cards = [], [], []
    for p in prospects:
        try:
            asset = engine.process_prospect(p, provider, model, brand, OUT_DIR, api_key)
            succeeded.append(asset)
            all_assets.append(asset)
            png = (OUT_DIR / asset.thumbnail_path).read_bytes()
            cards.append({
                "company": p.company, "first_name": p.first_name, "role": p.role,
                "industry": p.industry, "signal": asset.signal,
                "signal_source": asset.signal_source, "subject": asset.subject,
                "stages": asset.stages, "spoken": engine.spoken_script(asset),
                "thumbnail": "data:image/png;base64," + base64.b64encode(png).decode(),
                "status": "ok", "error": "",
            })
        except Exception as e:  # one bad prospect shouldn't sink the batch
            all_assets.append(engine.Asset(prospect=p, status="failed", error=str(e)))
            cards.append({
                "company": p.company, "first_name": p.first_name, "role": p.role,
                "status": "failed", "error": str(e),
            })

    engine.write_scripts_md(succeeded, OUT_DIR / "scripts.md")
    engine.write_results_csv(all_assets, OUT_DIR / "results.csv")
    engine.write_gallery_html(succeeded, brand, OUT_DIR / "gallery.html", OUT_DIR)

    return {
        "summary": {"ok": len(succeeded), "failed": len(all_assets) - len(succeeded)},
        "assets": cards,
        "bundle": "/download/bundle.zip",
    }


def _bundle_zip():
    """Zip the current output/ directory into memory for download."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(OUT_DIR.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(OUT_DIR))
    return buf.getvalue()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, content_type="application/json"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, (WEB_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/download/bundle.zip":
            if not OUT_DIR.exists():
                self._send(404, "Nothing generated yet.", "text/plain")
                return
            body = _bundle_zip()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", "attachment; filename=video-prospecting-output.zip")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._send(404, "Not found.", "text/plain")

    def do_POST(self):
        if self.path != "/api/generate":
            self._send(404, "Not found.", "text/plain")
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            result = _run_pipeline(payload)
            self._send(200, json.dumps(result))
        except Exception as e:  # surface engine/parse errors to the UI as JSON
            self._send(500, json.dumps({"error": str(e)}))

    def log_message(self, *args):
        pass  # quiet; and never log request bodies (they may carry an API key)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://localhost:{port}"
    print(f"Video Prospecting Engine — web UI running at {url}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
