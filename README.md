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

## The daily refresh

The Claude scheduled task runs at 9 AM, reads the calendar, inbox and objectives
list, writes `data/brief.json`, rebuilds `docs/index.html` and pushes. Pages
redeploys, and the icon on your home screen opens onto today.

The service worker serves the last-fetched copy when there's no signal, so the
brief is still there on a train or in a lift.

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
