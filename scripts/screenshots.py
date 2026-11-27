"""Regenerate the README screenshots from the demo thesis (examples/demo-thesis).

    pip install playwright            # once; uses any installed Chromium-based browser, or `playwright install chromium`
    python3 scripts/screenshots.py    # writes docs/screenshots/*.png

Set ATW_BROWSER to a Chromium-based browser binary (Chrome, Brave, Edge) to skip `playwright install`.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
WS = ROOT / "examples" / "demo-thesis"
OUT = ROOT / "docs" / "screenshots"
PORT = 8798
BASE = f"http://127.0.0.1:{PORT}/"

CANDIDATES = [
    os.environ.get("ATW_BROWSER", ""),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]

# name, hash route, optional clicks before the shot, optional full page
SHOTS = [
    ("overview", "#overview", [], False),
    ("manuscript", "#manuscript/1", [], False),
    ("comment-thread", "#manuscript/1", ["mark.cmt >> nth=0"], False),
    ("to-close", "#queue", [], False),
    ("decision-question", "#decisions?thread=CH3_PLAN.md&q=Q2", [], False),
    ("quality", "#quality", [], False),
    ("literature", "#literature", [], False),
    ("agents", "#agents", [], False),
]


def main() -> int:
    env = {**os.environ, "PYTHONPATH": str(ROOT), "ATW_SIGNING_KEY": str(WS / ".thesis" / "demo-signing.key")}
    srv = subprocess.Popen([sys.executable, "-m", "atw", "serve", "--workspace", str(WS), "--port", str(PORT)],
                           env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(BASE + "api/etag", timeout=1)
                break
            except Exception:
                time.sleep(0.2)
        OUT.mkdir(parents=True, exist_ok=True)
        exe = next((c for c in CANDIDATES if c and Path(c).exists()), None)
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2,
                                    color_scheme="light")
            for name, route, clicks, full in SHOTS:
                page.goto(BASE + route)
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(600)
                for sel in clicks:
                    page.locator(sel).click()
                    page.wait_for_timeout(500)
                page.screenshot(path=str(OUT / f"{name}.png"), full_page=full)
                print("wrote", (OUT / f"{name}.png").relative_to(ROOT))
            browser.close()
    finally:
        srv.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
