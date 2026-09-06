#!/usr/bin/env python3
"""
Build the deployed app: data/brief.json -> docs/index.html

    python3 scripts/build.py                    # uses data/brief.json
    python3 scripts/build.py data/brief.sample.json

Falls back to the sample payload when no real brief has been written yet, so a
fresh clone builds a working page. The rendered page is the whole app — one
self-contained HTML file plus the manifest, icons and service worker already
sitting in docs/.
"""
import os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RENDER = os.path.join(ROOT, "skill", "assets", "render.py")
OUT = os.path.join(ROOT, "docs", "index.html")

payload = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "brief.json")
if not os.path.exists(payload):
    sample = os.path.join(ROOT, "data", "brief.sample.json")
    print(f"no {os.path.relpath(payload, ROOT)} — falling back to the sample payload")
    payload = sample

subprocess.run([sys.executable, RENDER, payload, OUT, "--pwa"], check=True)
print(f"built {os.path.relpath(OUT, ROOT)}")
