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

A stage may carry `event_id`/`calendar_id` too, when the routine came from a
real recurring calendar block. It gets no buttons — it's how the live sync
tells an event already on the page from one added since the build. Set it
whenever the routine has a real event behind it.
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
# data-event-id (real calendar events the rebuild attached an id to) get action
# buttons; objectives/asks/prep quests have nothing to write back to.
#
# On connect — and on every reload that restores a live token — it also
# reconciles the page against the calendar as it stands right now: quests whose
# events are done or gone get marked, moved events show their new time, and
# anything added since the last rebuild is listed. That's the factual layer
# only; the prose stays as the last rebuild wrote it.
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

  // The token itself is kept (with its expiry) so a reload doesn't drop the
  // connection. Silent re-auth via a hidden iframe is not an option here:
  // Safari blocks the third-party cookies it depends on, which is exactly why
  // reloading used to disconnect. Scope is calendar.events only, it expires in
  // about an hour, and it never leaves this device.
  var TOKEN_KEY = 'dayrunCalToken';

  function saveToken(token, expiresIn) {
    try {
      localStorage.setItem(TOKEN_KEY, JSON.stringify({
        t: token,
        // 60s of headroom so a token can't expire mid-request
        exp: Date.now() + ((parseInt(expiresIn, 10) || 3600) - 60) * 1000
      }));
    } catch (e) {}
  }

  function loadToken() {
    try {
      var o = JSON.parse(localStorage.getItem(TOKEN_KEY) || 'null');
      if (!o || !o.t || !o.exp || Date.now() >= o.exp) return null;
      return o.t;
    } catch (e) { return null; }
  }

  function clearToken() { try { localStorage.removeItem(TOKEN_KEY); } catch (e) {} }

  function disconnect(msg) {
    accessToken = null;
    clearToken();
    setStatus(msg || 'CONNECT CALENDAR', false);
  }

  function onConnected() {
    setStatus('CALENDAR CONNECTED', true);
    revealActions();
    syncLive();
  }

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
          saveToken(resp.access_token, resp.expires_in);
          onConnected();
        }
      }
    });
    if (btn) btn.disabled = false;
    if (!accessToken) setStatus('CONNECT CALENDAR', false);
  }

  if (btn) btn.addEventListener('click', function () {
    if (!tokenClient) return;
    tokenClient.requestAccessToken({ prompt: accessToken ? '' : 'consent' });
  });

  // ── talking to the calendar ─────────────────────────────────────────────
  function authed(extra) {
    var h = { 'Authorization': 'Bearer ' + accessToken };
    if (extra) for (var k in extra) h[k] = extra[k];
    return h;
  }

  function handle(r) {
    if (r.status === 401) { disconnect('RECONNECT CALENDAR'); throw new Error('token expired'); }
    if (!r.ok) throw new Error('calendar api ' + r.status);
    return r.json();
  }

  function eventUrl(calId, eventId) {
    return 'https://www.googleapis.com/calendar/v3/calendars/' + encodeURIComponent(calId) +
           '/events/' + encodeURIComponent(eventId);
  }

  function patchEvent(calId, eventId, body) {
    return fetch(eventUrl(calId, eventId), {
      method: 'PATCH',
      headers: authed({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body)
    }).then(handle);
  }

  function shiftEvent(calId, eventId, minutes) {
    return fetch(eventUrl(calId, eventId), { headers: authed() }).then(handle)
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

  // ── live reconciliation ─────────────────────────────────────────────────
  // Everything below treats calendar text as data: summaries are escaped
  // before they ever touch innerHTML, exactly as the Python renderer does.
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function pad(n) { return (n < 10 ? '0' : '') + n; }

  function dayBounds() {
    // Today as it reads on a Nairobi wall clock (fixed UTC+3, no DST) — the
    // same day the rebuild renders, whatever timezone this phone is in.
    var d = new Date(Date.now() + 3 * 3600 * 1000);
    var ymd = d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate());
    return { min: ymd + 'T00:00:00+03:00', max: ymd + 'T23:59:59+03:00' };
  }

  function clockOf(iso) {
    try {
      return new Date(iso).toLocaleTimeString('en-US',
        { hour: 'numeric', minute: '2-digit', timeZone: 'Africa/Nairobi' });
    } catch (e) { return ''; }
  }

  function timeLabel(ev) {
    if (!ev.start || !ev.start.dateTime) return 'ALL DAY';
    return (clockOf(ev.start.dateTime) + '–' + clockOf(ev.end.dateTime)).toUpperCase();
  }

  // A stage contains its quests, so the head (and any existing chip) has to be
  // looked up by panel type and scoped to that header — searching the whole
  // panel would let a routine reach down into one of its own quests.
  function headOf(panel) {
    return panel.classList.contains('quest')
      ? panel.querySelector('.quest-head')
      : panel.querySelector('.stage-name');
  }

  function chip(panel, text) {
    var head = headOf(panel);
    if (!head) return;
    var el = head.querySelector('.live-chip');
    if (!text) { if (el) el.remove(); return; }
    if (!el) {
      el = document.createElement('span');
      el.className = 'live-chip';
      head.appendChild(el);
    }
    el.textContent = text;
  }

  function panelFor(el) { return el.closest('.quest') || el.closest('.stage'); }

  function syncLive() {
    if (!accessToken) return;
    var b = dayBounds();
    var url = 'https://www.googleapis.com/calendar/v3/calendars/primary/events' +
      '?timeMin=' + encodeURIComponent(b.min) +
      '&timeMax=' + encodeURIComponent(b.max) +
      '&singleEvents=true&orderBy=startTime&maxResults=50';
    fetch(url, { headers: authed() }).then(handle).then(reconcile).catch(function (err) {
      console.error(err);
    });
  }

  function reconcile(data) {
    var items = (data && data.items) || [];
    var byId = {};
    items.forEach(function (ev) { byId[ev.id] = ev; });

    var known = {};
    document.querySelectorAll('[data-event-id]').forEach(function (el) {
      var id = el.getAttribute('data-event-id');
      known[id] = true;
      var panel = panelFor(el);
      if (!panel) return;
      // These marker classes are deliberately not done/live/next — those
      // belong to the clock script, which strips any it doesn't own.
      panel.classList.remove('live-done', 'live-gone');
      var ev = byId[id];
      if (!ev || ev.status === 'cancelled') {
        panel.classList.add('live-gone');
        chip(panel, 'OFF THE CALENDAR');
        return;
      }
      var p = ev.extendedProperties && ev.extendedProperties.private;
      if (p && p.dayrunDone === '1') {
        panel.classList.add('live-done');
        chip(panel, 'DONE');
      } else {
        // A quest shows the event's current time (so a moved one reads true);
        // a routine already prints its range, so it stays unmarked when normal.
        chip(panel, panel.classList.contains('quest') ? timeLabel(ev) : '');
      }
    });

    renderExtras(items.filter(function (ev) {
      return !known[ev.id] && ev.status !== 'cancelled' && ev.start && ev.start.dateTime;
    }));

    var n = new Date();
    setStatus('SYNCED ' + clockOf(n.toISOString()).toUpperCase(), true);
  }

  // Anything on the calendar today that the last rebuild didn't know about.
  // Listed plainly, in the calendar's own words — no invented framing, since
  // writing the brief's prose is the rebuild's job, not this script's.
  function renderExtras(extras) {
    var host = document.getElementById('live-extras');
    if (!host) return;
    if (!extras.length) { host.hidden = true; host.innerHTML = ''; return; }
    host.innerHTML = '<div class="sec-label"><span>SINCE LAST BUILD</span><i></i></div>' +
      extras.map(function (ev) {
        return '<div class="quest">' +
          '<div class="quest-head"><span class="quest-sig">◆ NEW</span>' +
          '<span class="quest-title">' + esc(ev.summary || '(untitled)') + '</span></div>' +
          '<div class="quest-body">' + esc(timeLabel(ev)) + ' — on your calendar, added since this page was last built.</div>' +
          '<div class="quest-actions" data-event-id="' + esc(ev.id) + '" data-calendar-id="primary">' +
          '<button data-cal-action="done">✓ DONE</button>' +
          '<button data-cal-action="snooze">+30 MIN</button></div></div>';
      }).join('');
    host.hidden = false;
  }

  // ── actions ─────────────────────────────────────────────────────────────
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
      t.disabled = false;
      syncLive();  // re-read the calendar so the page shows what actually landed
    }).catch(function (err) {
      t.disabled = false;
      t.textContent = 'RETRY';
      console.error(err);
    });
  });

  window.addEventListener('load', function () {
    // A stored, unexpired token means this device is still connected — restore
    // it before Google's script even loads, so a reload never looks logged out.
    var stored = loadToken();
    if (stored) { accessToken = stored; onConnected(); }
    var tries = 0;
    (function poll() {
      if (window.google && google.accounts && google.accounts.oauth2) return ready();
      if (++tries > 40) { if (!accessToken) setStatus('CALENDAR SYNC UNAVAILABLE', false); return; }
      setTimeout(poll, 125);
    })();
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
        # A routine that came from a real calendar block carries its event id
        # too — not for action buttons, but so the live sync can tell "this is
        # already on the page" from "this is new since the build".
        ev = (f' data-event-id="{esc(s["event_id"])}"'
              f' data-calendar-id="{esc(s.get("calendar_id", "primary"))}"') if s.get("event_id") else ""
        out.append(f'''
    <div class="stage {s["_state"]}" data-s="{s["s"]}" data-e="{s["e"]}"{ev}>
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
