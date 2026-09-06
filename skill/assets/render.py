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
     "quests": [{"sig": "TIME-BOUND", "title": "≤10 words", "body": "One sentence.",
                 "event_id": "abc123", "calendar_id": "primary"}]}
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

`event_id`/`calendar_id` on a quest are optional and only make sense for a
quest sourced from a real calendar event (a TIME-BOUND quest, not an
objective/ask/prep one) — in --pwa builds they attach Done/+30min controls
that write back to that exact event via the Google Calendar API, straight
from the browser. Omit both for quests with nothing to write back to.
"""

import base64, html, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CELL_CLASSES = ["boss", "main", "side", "arch"]

# Shared with the client-side live-clock script (LIVE_JS below), which
# re-derives the same route geometry from data-* attributes using the
# viewer's real clock — these constants must stay in lockstep with the JS copy.
ROUTE_X0, ROUTE_X1, ROUTE_XA, ROUTE_XB = 60.0, 880.0, 20.0, 920.0

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
<script src="config.js"></script>
<script>
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('sw.js').catch(function () {});
    });
  }
</script>"""

# Connect button sitting in the HUD row. Disabled until config.js + the Google
# script both check out, so a broken setup fails visibly instead of dead-clicking.
CAL_UI = '<button id="cal-connect" class="cal-connect" disabled>CALENDAR SYNC…</button>'

# Real write-back to Google Calendar, straight from the browser — no backend.
# Uses Google Identity Services' token-client flow (a public, PKCE-style client;
# the Client ID in config.js is not a secret). Only quests carrying a
# data-event-id (real calendar events the daily rebuild attached an id to) get
# action buttons; objectives/asks/prep quests have nothing to write back to.
CAL_JS = """<script src="https://accounts.google.com/gsi/client" async defer></script>
<script>
(function () {
  var CLIENT_ID = window.DAYRUN_GOOGLE_CLIENT_ID || '';
  var SCOPE = 'https://www.googleapis.com/auth/calendar.events';
  var tokenClient = null, accessToken = null;
  var btn = document.getElementById('cal-connect');

  function setStatus(text, connected) {
    if (!btn) return;
    btn.textContent = text;
    btn.classList.toggle('connected', !!connected);
  }

  function revealActions() {
    document.querySelectorAll('.quest-actions').forEach(function (el) { el.hidden = false; });
  }

  // sessionStorage remembers only "this browser has granted before" — never a
  // token, which always stays in memory and is gone the instant the tab is.
  var GRANTED_KEY = 'dayrunCalGranted';
  function rememberGrant() { try { sessionStorage.setItem(GRANTED_KEY, '1'); } catch (e) {} }
  function everGranted() { try { return sessionStorage.getItem(GRANTED_KEY) === '1'; } catch (e) { return false; } }

  function ready() {
    if (!CLIENT_ID || !window.google || !google.accounts || !google.accounts.oauth2) {
      setStatus('CALENDAR SYNC UNCONFIGURED', false);
      return;
    }
    tokenClient = google.accounts.oauth2.initTokenClient({
      client_id: CLIENT_ID,
      scope: SCOPE,
      callback: function (resp) {
        if (resp && resp.access_token) {
          accessToken = resp.access_token;
          setStatus('CALENDAR CONNECTED', true);
          rememberGrant();
          revealActions();
        } else if (!everGranted()) {
          // A failed silent attempt with no prior grant on this device is
          // expected (never connected yet) — leave the button as an invite.
          setStatus('CONNECT CALENDAR', false);
        }
      }
    });
    setStatus('CONNECT CALENDAR', false);
    if (btn) btn.disabled = false;
    // A page reload loses the in-memory token but not Google's own consent —
    // if this browser connected before, reclaim a token with no popup at all.
    if (everGranted()) tokenClient.requestAccessToken({ prompt: 'none' });
  }

  window.addEventListener('load', function () {
    var tries = 0;
    (function poll() {
      if (window.google && google.accounts && google.accounts.oauth2) return ready();
      if (++tries > 40) return setStatus('CALENDAR SYNC UNAVAILABLE', false);
      setTimeout(poll, 125);
    })();
  });

  if (btn) btn.addEventListener('click', function () {
    if (!tokenClient) return;
    tokenClient.requestAccessToken({ prompt: accessToken ? '' : 'consent' });
  });

  function api(calId, eventId, opts) {
    return fetch(
      'https://www.googleapis.com/calendar/v3/calendars/' + encodeURIComponent(calId) +
      '/events/' + encodeURIComponent(eventId),
      opts
    ).then(function (r) {
      if (!r.ok) throw new Error('calendar api ' + r.status);
      return r.json();
    });
  }

  function patchEvent(calId, eventId, body) {
    return api(calId, eventId, {
      method: 'PATCH',
      headers: { 'Authorization': 'Bearer ' + accessToken, 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
  }

  function shiftEvent(calId, eventId, minutes) {
    return api(calId, eventId, { headers: { 'Authorization': 'Bearer ' + accessToken } })
      .then(function (ev) {
        if (!ev.start.dateTime) throw new Error('all-day event');
        var s = new Date(ev.start.dateTime), e = new Date(ev.end.dateTime);
        s.setMinutes(s.getMinutes() + minutes);
        e.setMinutes(e.getMinutes() + minutes);
        return patchEvent(calId, eventId, {
          start: { dateTime: s.toISOString(), timeZone: ev.start.timeZone },
          end: { dateTime: e.toISOString(), timeZone: ev.end.timeZone }
        });
      });
  }

  document.addEventListener('click', function (e) {
    var t = e.target.closest('[data-cal-action]');
    if (!t) return;
    var holder = t.closest('[data-event-id]');
    if (!holder) return;
    if (!accessToken) { setStatus('CONNECT CALENDAR FIRST', false); return; }
    var calId = holder.getAttribute('data-calendar-id') || 'primary';
    var eventId = holder.getAttribute('data-event-id');
    var action = t.getAttribute('data-cal-action');
    t.disabled = true;
    var op = action === 'done'
      ? patchEvent(calId, eventId, { extendedProperties: { private: { dayrunDone: '1' } } })
      : shiftEvent(calId, eventId, 30);
    op.then(function () {
      if (action === 'done') { holder.style.opacity = '.4'; t.textContent = 'DONE'; }
      else { t.disabled = false; t.textContent = '+30 MIN \\u2713'; setTimeout(function () { t.textContent = '+30 MIN'; }, 1500); }
    }).catch(function (err) {
      t.disabled = false;
      t.textContent = 'RETRY';
      console.error(err);
    });
  });
})();
</script>"""

# Between rebuilds (now hourly, but never instant) the page otherwise shows
# whatever time it was when it was last built. This recomputes only the
# clock-driven visual state — which stage/node is done/live/next, the NOW
# marker, the progress trail, the HUD pips and DAY% — against the viewer's
# actual current time, on load and every minute. It never touches content
# (headline, quests, log lines): that stays exactly what the last rebuild
# wrote, since deciding *what* today's brief says is Claude's job, not a
# formula a public page can safely run for anyone who opens it.
LIVE_JS = """<script>
(function () {
  var X0 = __X0__, X1 = __X1__, XA = __XA__, XB = __XB__;
  var route = document.querySelector('.route-frame');
  var trail = document.querySelector('.trail-hot');
  var pips = document.querySelector('.pips');
  var pct = document.querySelector('.hud-pct');
  var nowmark = document.getElementById('nowmark');
  var nowRule = document.getElementById('now-rule');
  var nowTag = document.getElementById('now-tag');
  if (!route || !trail) return;
  var spanS = parseFloat(route.dataset.spanS), spanE = parseFloat(route.dataset.spanE);

  function xpos(t) { return X0 + (t - spanS) / Math.max(spanE - spanS, 0.01) * (X1 - X0); }

  // Africa/Nairobi is fixed UTC+3 year-round (no DST) — this is the same
  // clock the daily rebuild uses, computed from the viewer's own device
  // clock so it's correct regardless of the phone's local timezone.
  function nowNairobi() {
    var d = new Date();
    return ((d.getUTCHours() + d.getUTCMinutes() / 60 + d.getUTCSeconds() / 3600) + 3) % 24;
  }

  function tick() {
    var now = nowNairobi();
    var nowX = xpos(now);
    var elapsed = Math.max(0, Math.min(100, (nowX - XA) / (XB - XA) * 100));

    document.querySelectorAll('[data-s][data-e]').forEach(function (el) {
      var s = parseFloat(el.dataset.s), e = parseFloat(el.dataset.e);
      var state = e <= now ? 'done' : (s <= now && now <= e ? 'live' : 'next');
      el.classList.remove('done', 'live', 'next');
      el.classList.add(state);
    });

    trail.setAttribute('stroke-dasharray', elapsed.toFixed(1) + ' 100');

    if (nowmark && nowRule && nowTag) {
      nowmark.style.display = (elapsed > 0 && elapsed < 100) ? 'block' : 'none';
      nowRule.setAttribute('x1', nowX.toFixed(1));
      nowRule.setAttribute('x2', nowX.toFixed(1));
      nowTag.setAttribute('x', (nowX + 7).toFixed(1));
    }

    if (pips) {
      var lit = Math.round(elapsed / 100 * 28);
      Array.prototype.forEach.call(pips.children, function (pip, k) {
        pip.classList.toggle('on', k < lit);
      });
    }
    if (pct) pct.textContent = 'DAY ' + Math.round(elapsed) + '%';
  }

  tick();
  setInterval(tick, 60000);
})();
</script>""".replace("__X0__", str(ROUTE_X0)).replace("__X1__", str(ROUTE_X1)) \
             .replace("__XA__", str(ROUTE_XA)).replace("__XB__", str(ROUTE_XB))


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
    X0, X1, XA, XB = ROUTE_X0, ROUTE_X1, ROUTE_XA, ROUTE_XB
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

    nodes = []
    for s in stages:
        cx, cy = xpos((s["s"] + s["e"]) / 2), s["_y"]
        s["_state"] = "done" if s["e"] <= now else ("live" if s["s"] <= now <= s["e"] else "next")
        # One uniform shape per node (halo + ring + core dot) regardless of
        # state — CSS keyed off the state class on the <g> controls which
        # parts show. This is what lets the live-clock script simply swap
        # that one class every minute instead of rebuilding the markup.
        nodes.append(
            f'<g class="node {s["_state"]}" data-s="{s["s"]}" data-e="{s["e"]}">'
            f'<circle class="node-halo" cx="{cx:.1f}" cy="{cy:.1f}" r="15"/>'
            f'<circle class="node-ring" cx="{cx:.1f}" cy="{cy:.1f}"/>'
            f'<circle class="node-core" cx="{cx:.1f}" cy="{cy:.1f}" r="3"/>'
            f'<text class="node-cap node-cap-name" x="{cx:.1f}" y="152" text-anchor="middle">'
            f'{esc(s["name"].split()[0])}</text>'
            f'<text class="node-cap" x="{cx:.1f}" y="167" text-anchor="middle">'
            f'{esc(time_range(s["s"], s["e"]).replace(" – ", "–"))}</text>'
            f'</g>')

    # Always present (JS toggles visibility each tick); the initial SSR
    # position/visibility below is just this render's starting frame.
    nowmark = (f'<g id="nowmark" style="display:{"block" if 0 < elapsed < 100 else "none"}">'
               f'<line id="now-rule" class="now-rule" x1="{now_x:.1f}" y1="16" x2="{now_x:.1f}" y2="138"/>'
               f'<text id="now-tag" class="now-tag" x="{now_x + 7:.1f}" y="22">NOW</text></g>')

    return catmull_rom(pts), elapsed, nowmark, "".join(nodes), span_s, span_e


# ── markup ────────────────────────────────────────────────────────────────
def render_quest_actions(q, pwa):
    """A quest tied to a real calendar event (event_id set) gets Done/+30min
    controls that write straight back to that event. Hidden until the PWA's
    calendar-sync script confirms a connection; nothing renders in a portable,
    non-pwa export or for quests with no source event to act on."""
    if not pwa or not q.get("event_id"):
        return ""
    return (f'<div class="quest-actions" hidden data-event-id="{esc(q["event_id"])}" '
            f'data-calendar-id="{esc(q.get("calendar_id", "primary"))}">'
            f'<button data-cal-action="done">✓ DONE</button>'
            f'<button data-cal-action="snooze">+30 MIN</button></div>')


def render_stages(stages, pwa=False):
    out = []
    for i, s in enumerate(stages, 1):
        quests = "".join(f'''<div class="quest">
          <div class="quest-head"><span class="quest-sig">◆ {esc(q.get("sig", "QUEST"))}</span><span class="quest-title">{esc(q["title"])}</span></div>
          <div class="quest-body">{q["body"] if q.get("html") else esc(q["body"])}</div>
          {render_quest_actions(q, pwa)}
        </div>''' for q in s.get("quests", []))
        out.append(f'''
    <div class="stage {s["_state"]}" data-s="{s["s"]}" data-e="{s["e"]}">
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
    trail, elapsed, nowmark, nodes, span_s, span_e = build_route(stages, data["now"])

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
              .replace("__CAL_UI__", CAL_UI if pwa else "")
              .replace("__CAL_JS__", CAL_JS if pwa else "")
              .replace("__LIVE_JS__", LIVE_JS if pwa else "")
              .replace("__RUN__", str(data.get("run", "")))
              .replace("__DATE__", esc(data.get("date", "")))
              .replace("__HEADLINE__", render_headline(data["headline"], data.get("emphasis")))
              .replace("__SPAN_S__", str(span_s))
              .replace("__SPAN_E__", str(span_e))
              .replace("__TRAIL__", trail)
              .replace("__ELAPSED__", f"{elapsed:.1f}")
              .replace("__NOWMARK__", nowmark)
              .replace("__NODES__", nodes)
              .replace("__STAGES__", render_stages(stages, pwa))
              .replace("__GRID__", grid)
              .replace("__PIPS__", pips)
              .replace("__STATS__", stats)
              .replace("__PCT__", str(round(elapsed))))

    open(out_path, "w").write(out)
    print(f"{out_path} · {len(out)} chars · {round(elapsed)}% elapsed · "
          f"{n_quests} quests · {n_triage} triage · {n_arch} archived")


if __name__ == "__main__":
    main()
