#!/usr/bin/env python3
"""
Render the morning brief run-screen from a JSON payload.

    python3 render.py brief.json out.html [--pwa] [--font path/to/fraunces-latin-600-normal.woff2]

The JSON carries only content and times; every bit of geometry (route spline,
node states, progress meter, HUD counts) is derived here so the trail always
passes exactly through its nodes and the numbers always match what renders.

Payload shape — times are floats in 24h decimal hours (9.5 == 9:30 AM):

{
  "run": 231,                       // day of year; identity for the run
  "date": "WED · 19 AUG 2026",
  "now": 9.0,                       // render time, drives live/cleared states
  "headline": "Two blocks carry the whole day, and the afternoon is yours to spend.",
  "emphasis": "yours to spend",     // trailing phrase set in ember (optional)
  "stages": [
    {"name": "CONTROL BLOCK", "tag": "PLAN", "s": 15.5, "e": 17.0, "load": 0.55,
     "log": "One sentence earned from the calendar.",
     "quests": [{"sig": "TIME-BOUND", "title": "≤10 words", "body": "One sentence."}]}
  ],
  "cells": [                        // omit entirely to drop the grid
    {"rank": "BOSS", "axis": "URGENT · IMPORTANT", "items": [{"title": "...", "body": "..."}]},
    {"rank": "MAIN QUEST", "axis": "IMPORTANT · NOT URGENT", "items": []},
    {"rank": "SIDE QUEST", "axis": "URGENT · NOT IMPORTANT", "items": []},
    {"rank": "ARCHIVE", "axis": "NEITHER", "items": []}
  ]
}

`load` is 0..1 (how demanding the routine is) and sets the node's height on the
trail. Leave it out and it's inferred from duration.
"""

import base64, html, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CELL_CLASSES = ["boss", "main", "side", "arch"]

PWA_HEAD = """<link rel="manifest" href="manifest.webmanifest">
<meta name="theme-color" content="#0B0E14">
<meta name="color-scheme" content="dark">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Day Run">
<link rel="apple-touch-icon" href="icons/apple-touch-icon-180.png">
<link rel="icon" type="image/svg+xml" href="favicon.svg">
<link rel="icon" type="image/png" sizes="192x192" href="icons/icon-192.png">
<script>
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('sw.js').catch(function () {});
    });
  }
</script>"""


def esc(s):
    return html.escape(str(s), quote=True)


# ── time helpers ──────────────────────────────────────────────────────────
def _clock(t):
    h, m = int(t), round((t % 1) * 60)
    if m == 60:
        h, m = h + 1, 0
    ap = "AM" if h % 24 < 12 else "PM"
    hh = h % 12 or 12
    return (f"{hh}:{m:02d}" if m else f"{hh}"), ap


def time_range(s, e):
    """9:30 AM – 1 PM · 1 – 3:30 PM — AM/PM on the tail, and on the head only
    when the range crosses noon."""
    (a, ap), (b, bp) = _clock(s), _clock(e)
    return f"{a} {ap} – {b} {bp}" if ap != bp else f"{a} – {b} {bp}"


# ── route geometry ────────────────────────────────────────────────────────
def catmull_rom(points):
    """One unbroken cubic path through every point — nodes sit on the trail."""
    d = f"M {points[0][0]:.1f},{points[0][1]:.1f}"
    for i in range(len(points) - 1):
        p0 = points[i - 1] if i > 0 else points[0]
        p1, p2 = points[i], points[i + 1]
        p3 = points[i + 2] if i + 2 < len(points) else points[-1]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        d += f" C {c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}"
    return d


def build_route(stages, now):
    X0, X1, XA, XB = 60.0, 880.0, 20.0, 920.0
    span_s = min(s["s"] for s in stages)
    span_e = max(s["e"] for s in stages)

    def xpos(t):
        return X0 + (t - span_s) / max(span_e - span_s, 0.01) * (X1 - X0)

    # y: high load rides high on the ridge (small y), light load sits low
    for s in stages:
        load = s.get("load")
        if load is None:
            load = min(1.0, (s["e"] - s["s"]) / 3.0)
        s["_y"] = 118.0 - 62.0 * max(0.0, min(1.0, float(load)))

    pts = [(XA, 132.0)]
    for i, s in enumerate(stages):
        if i:
            gap = s["s"] - stages[i - 1]["e"]
            if gap > 1.5:  # an open stretch should read as a valley, not a slope
                mid = (stages[i - 1]["e"] + s["s"]) / 2
                pts.append((xpos(mid), min(134.0, 112.0 + gap * 5.0)))
        pts.append((xpos((s["s"] + s["e"]) / 2), s["_y"]))
    pts.append((XB, 128.0))

    now_x = xpos(now)
    elapsed = max(0.0, min(100.0, (now_x - XA) / (XB - XA) * 100.0))

    nodes, caps = [], []
    for s in stages:
        cx, cy = xpos((s["s"] + s["e"]) / 2), s["_y"]
        s["_state"] = "done" if s["e"] <= now else ("live" if s["s"] <= now <= s["e"] else "next")
        if s["_state"] == "done":
            nodes.append(f'<circle class="node-done" cx="{cx:.1f}" cy="{cy:.1f}" r="6.5"/>')
        elif s["_state"] == "live":
            nodes.append(
                f'<circle class="node-halo" cx="{cx:.1f}" cy="{cy:.1f}" r="15"/>'
                f'<circle class="node-live" cx="{cx:.1f}" cy="{cy:.1f}" r="8"/>'
                f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3" fill="#58D6C9"/>')
        else:
            nodes.append(f'<circle class="node-next" cx="{cx:.1f}" cy="{cy:.1f}" r="6"/>')
        caps.append(
            f'<text class="node-cap {s["_state"]}" x="{cx:.1f}" y="152" text-anchor="middle">'
            f'{esc(s["name"].split()[0])}</text>'
            f'<text class="node-cap" x="{cx:.1f}" y="167" text-anchor="middle">'
            f'{esc(time_range(s["s"], s["e"]).replace(" – ", "–"))}</text>')

    nowmark = ""
    if 0 < elapsed < 100:
        nowmark = (f'<line class="now-rule" x1="{now_x:.1f}" y1="16" x2="{now_x:.1f}" y2="138"/>'
                   f'<text class="now-tag" x="{now_x + 7:.1f}" y="22">NOW</text>')

    return catmull_rom(pts), elapsed, nowmark, "".join(nodes) + "".join(caps)


# ── markup ────────────────────────────────────────────────────────────────
def render_stages(stages):
    out = []
    for i, s in enumerate(stages, 1):
        quests = "".join(f'''<div class="quest">
          <div class="quest-head"><span class="quest-sig">◆ {esc(q.get("sig", "QUEST"))}</span><span class="quest-title">{esc(q["title"])}</span></div>
          <div class="quest-body">{q["body"] if q.get("html") else esc(q["body"])}</div>
        </div>''' for q in s.get("quests", []))
        out.append(f'''
    <div class="stage {s["_state"]}">
      <div class="idx">{i:02d}</div>
      <div>
        <div class="stage-name">{esc(s["name"])}<span class="tag">{esc(s.get("tag", ""))}</span></div>
        <div class="stage-log">{esc(s["log"])}</div>
      </div>
      <div class="stage-time">{esc(time_range(s["s"], s["e"]))}</div>
      {quests}
    </div>''')
    return "".join(out)


def render_cells(cells):
    out = []
    for c, cls in zip(cells, CELL_CLASSES):
        items = c.get("items", [])
        body = "".join(f'''<div class="slot"><div class="slot-n">{j:02d}</div><div>
              <div class="slot-title">{esc(it["title"])}</div>
              <div class="slot-body">{it["body"] if it.get("html") else esc(it["body"])}</div></div></div>'''
                       for j, it in enumerate(items, 1)) or '<div class="empty">EMPTY</div>'
        out.append(f'''
    <div class="cell {cls}">
      <div class="rank"><i class="sig"></i><b>{esc(c["rank"])}</b></div>
      <div class="axis">{esc(c["axis"])}</div>
      {body}
    </div>''')
    return "".join(out)


def render_headline(text, emphasis):
    safe = esc(text)
    if emphasis and emphasis in text:
        safe = esc(text).replace(esc(emphasis), f"<em>{esc(emphasis)}</em>", 1)
    return safe


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    data = json.load(open(args[0]))
    out_path = args[1] if len(args) > 1 else "brief.html"
    font_path = next((sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--font"),
                     os.path.join(HERE, "fonts", "fraunces-latin-600-normal.woff2"))
    # --pwa wires up the manifest, iOS icon and service worker for the hosted,
    # installable copy. Without it the output stays a single portable file with
    # no external references, which is what gets handed over in chat.
    pwa = "--pwa" in sys.argv

    tpl = open(os.path.join(HERE, "template.html")).read()
    font_b64 = base64.b64encode(open(font_path, "rb").read()).decode() if os.path.exists(font_path) else ""

    stages = data["stages"]
    cells = data.get("cells") or []
    trail, elapsed, nowmark, nodes = build_route(stages, data["now"])

    n_quests = sum(len(s.get("quests", [])) for s in stages)
    n_triage = sum(len(c.get("items", [])) for c in cells[:3])
    n_arch = sum(len(c.get("items", [])) for c in cells[3:])
    stats = (f'<div class="stat"><b>{n_quests:02d}</b> QUESTS</div>'
             f'<div class="stat"><b>{n_triage:02d}</b> TRIAGE</div>'
             f'<div class="stat dim"><b>{n_arch:02d}</b> ARCHIVED</div>')
    pips = "".join(f'<i class="pip{" on" if k < round(elapsed / 100 * 28) else ""}"></i>' for k in range(28))

    grid = f'<div class="r" style="animation-delay:.36s; margin-top:54px">' \
           f'<div class="sec-label"><span>TRIAGE GRID</span><i></i></div>' \
           f'<div class="grid">{render_cells(cells)}</div></div>' if cells else ""

    out = (tpl.replace("__FONT_B64__", font_b64)
              .replace("__PWA_HEAD__", PWA_HEAD if pwa else "")
              .replace("__RUN__", str(data.get("run", "")))
              .replace("__DATE__", esc(data.get("date", "")))
              .replace("__HEADLINE__", render_headline(data["headline"], data.get("emphasis")))
              .replace("__TRAIL__", trail)
              .replace("__ELAPSED__", f"{elapsed:.1f}")
              .replace("__NOWMARK__", nowmark)
              .replace("__NODES__", nodes)
              .replace("__STAGES__", render_stages(stages))
              .replace("__GRID__", grid)
              .replace("__PIPS__", pips)
              .replace("__STATS__", stats)
              .replace("__PCT__", str(round(elapsed))))

    open(out_path, "w").write(out)
    print(f"{out_path} · {len(out)} chars · {round(elapsed)}% elapsed · "
          f"{n_quests} quests · {n_triage} triage · {n_arch} archived")


if __name__ == "__main__":
    main()
