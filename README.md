# Day Run

The morning brief as a run screen. Your routines are the stages, whatever needs
you today are quests sitting on them, and everything that doesn't anchor to a
routine falls into an urgent/important triage grid.

It installs to a phone home screen with its own icon and opens like an app.

<img src="docs/icons/icon-192.png" width="88" alt="Day Run icon">

## How it's put together

| Path | What it is |
|---|---|
| `docs/` | The deployed app. Static — this is what GitHub Pages serves. |
| `docs/index.html` | The brief itself: one self-contained file, fonts inlined, no CDN. |
| `docs/manifest.webmanifest` | Name, colours and icons that make it installable. |
| `docs/sw.js` | Service worker. Network-first, cache-fallback — opens on bad signal. |
| `docs/config.js` | Your Google OAuth Client ID for the in-app calendar-sync buttons. |
| `skill/` | The Claude skill that gathers the day and writes the payload. |
| `skill/assets/render.py` | Turns a JSON payload into the page. Owns all the geometry. |
| `skill/assets/template.html` | The design system: tokens, HUD, route, stages, grid, motion. |
| `data/brief.sample.json` | A fictional demo day, so a fresh clone builds something real. |
| `scripts/build.py` | `data/brief.json` → `docs/index.html`. |
| `scripts/make_icons.py` | Rasterises `docs/favicon.svg` into the PNG icon set. |

## Building

```bash
python3 scripts/build.py                      # uses data/brief.json, falls back to the sample
python3 scripts/build.py data/brief.sample.json
```

The renderer takes content and computes everything else — the route spline, which
stage is live, the progress meter, the HUD counts — so the numbers on screen can
never drift from what's actually in the payload.

```bash
python3 skill/assets/render.py data/brief.json out.html          # portable single file
python3 skill/assets/render.py data/brief.json docs/index.html --pwa   # + manifest, icons, SW
```

Payload shape is documented in the docstring at the top of `render.py`. Times are
decimal hours (`9.5` = 9:30 AM), `load` is 0–1 and sets a routine's height on the ridge.
A quest sourced from a real calendar event can also carry `event_id` / `calendar_id` —
see "Calendar sync from the PWA" below.

## Deploying

1. Push this repo to GitHub.
2. **Settings → Pages → Source: GitHub Actions.**
3. Push to `main`. The workflow in `.github/workflows/pages.yml` publishes `docs/`.

Your app lives at `https://<user>.github.io/day-run/`.

### Installing to the home screen

- **iOS Safari** — Share → Add to Home Screen. Uses `apple-touch-icon-180.png`,
  launches without browser chrome, dark status bar.
- **Android Chrome** — menu → Install app / Add to Home screen. Uses the maskable
  icon so it adapts to whatever shape the launcher wants.

## The refresh

A Claude Routine fires every 6 hours (9 AM / 3 PM / 9 PM / 3 AM Africa/Nairobi),
reads the calendar, inbox and objectives list, writes `data/brief.json`, rebuilds
`docs/index.html` and pushes to `main`. Pages redeploys, and the icon on your
home screen opens onto the latest run — including anything you changed from the
PWA itself since the last refresh.

The service worker serves the last-fetched copy when there's no signal, so the
brief is still there on a train or in a lift.

## Calendar sync from the PWA

Quests sourced from a real calendar event (not an objective or an email ask) get
two buttons — **✓ DONE** and **+30 MIN** — that write straight back to that event
in Google Calendar, from your phone, no server involved:

- **DONE** sets a private extended property (`dayrunDone`) on the event. The next
  refresh sees it and drops the quest instead of re-surfacing it.
- **+30 MIN** reads the event's current start/end and pushes both forward half an
  hour — a real reschedule, not just a note on the page.

The connection survives a reload: the token (calendar-scoped, ~1h, this device
only) is kept in `localStorage`, because the silent re-auth that would avoid
storing it needs third-party cookies that Safari blocks.

On connect — and on any reload that restores a live token — the page reconciles
itself against the calendar as it stands right now: quests whose events are
done or deleted get marked, a moved event shows its new time, and anything
added since the last build is listed under **SINCE LAST BUILD** in the
calendar's own words. That's the factual layer only. The prose — headline, log
lines, which event is worth being a quest — stays as the last rebuild wrote it,
because writing it means Claude reading the calendar, and a public page can't
be allowed to trigger that for whoever opens it.

This needs a one-time Google Cloud OAuth Client ID, since the buttons talk to
Google's Calendar API directly from your browser (no backend to hold a token for
you). Full steps are in `docs/config.js` — roughly: enable the Calendar API,
create an OAuth consent screen kept in **Testing** mode with only your own email
as a test user (this is what stops any other visitor to this public page from
being able to connect *their* calendar), create a Web application OAuth client
scoped to `https://<user>.github.io`, and paste the Client ID into `config.js`.

Until that's done, the HUD button reads `CALENDAR SYNC UNCONFIGURED` and nothing
else changes — the rest of the app works the same either way.

## A note on privacy before you deploy

The rendered page contains real content — your routines, what's in your inbox,
what you owe people. **GitHub Pages serves that page publicly**, and on a free
account Pages requires the repository to be public.

So there are three honest options:

1. **Keep the repo private.** Everything works locally; no public URL.
2. **Private repo + Pages.** Needs a paid GitHub plan; the site is still public
   unless you're on Enterprise with access control.
3. **Public repo.** Simplest path to an installable app, and it means your daily
   routine and inbox summaries are readable by anyone with the URL.

`data/brief.json` is gitignored so raw payloads never land here by accident, but
the *rendered* page is committed by design — that's what gets served. Decide
before the first real brief is pushed, not after.

## Licence

Personal project. The bundled Fraunces font is under the SIL Open Font License —
see `skill/assets/fonts/Fraunces-OFL.txt`.
