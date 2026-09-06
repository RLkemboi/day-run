# Multi-account Day Run: costs, requirements, weaknesses, and the road ahead

Written 2026-09-06. Scoped question: can Day Run manage **multiple email
inboxes and multiple calendars**, possibly across different accounts and
providers (Gmail, other Google accounts, Outlook/Microsoft 365, etc.)?

Short answer: partially, today, for free, in about 30 minutes — for the rest,
yes it's buildable, but the honest cost is mostly *yours* (setup, token
babysitting, growing attack surface), not money, and there's a cheaper path
than building it that gets most of the value.

## 1. What exists right now

- **One** Google Calendar connection, held by this Claude session, feeding a
  Routine that rebuilds the page every 6 hours.
- **One** client-side Google OAuth Client ID in `docs/config.js`, used by the
  PWA's Done/+30min buttons to write back to that same Google account's
  calendar (`calendar.events` scope, browser-side, no backend).
- **No** email integration at all yet — SKILL.md's Gather section supports
  Gmail/chat/objectives, but the Routine I set up was granted Calendar only,
  per the original ask.

Every quest already carries an optional `calendar_id` field (render.py), so
reading from a **second calendar the same Google account already has access
to** — a shared work calendar, a subscribed calendar — is close to free: no
new auth, no new accounts, just telling the Gather step to also pull that
calendar's events.

## 2. What "multiple inboxes/calendars" actually requires, broken down

### 2a. A second calendar under the *same* Google account
- **Requirement:** none beyond what's built. The existing OAuth grant already
  covers every calendar that account can see.
- **Cost:** ~30 minutes of prompt/render-pipeline changes. $0.
- **Weakness:** none new. This is the cheap 80% case if what you actually
  have is "a work calendar and a personal calendar on one Google login."

### 2b. A genuinely separate Google account (a second Gmail login entirely)
- **Server-side (the Routine's automated gather):** needs a second, distinct
  Google Calendar connector grant. Whether the platform lets one account hold
  two simultaneous named connections of the *same* connector type is the real
  open question — this session couldn't even pass connector grants explicitly
  to a routine (org policy blocked the `connectors` parameter outright), which
  is itself a sign this surface is locked down more than the API suggests.
  If claude.ai's connector settings only allow one "Google Calendar" link at
  a time, this path is blocked until that changes.
- **Client-side (PWA write-back):** technically fine — Google's identity
  library lets a page request a token for any account the user picks at the
  browser's account chooser, one at a time. You *could* add an account
  switcher and hold two tokens in memory. Real engineering, not a config
  change.
- **Cost:** medium. New UI (account switcher, per-account labeling on every
  quest/stage), updated payload schema (`source_account` field), updated
  Sort logic to merge and de-duplicate two calendars' events into one
  skeleton without double-counting a meeting that appears on both.
- **Requirement:** confirm the platform actually supports a second Calendar
  connector before writing a line of code — otherwise this is dead on arrival
  server-side and only half-works (PWA writes, but the daily render can't see
  the second account).

### 2c. Multiple email inboxes (Gmail)
- Same connector-multiplicity question as 2b, but higher stakes: email is a
  much bigger blast radius than calendar if anything goes wrong (whole
  message contents vs. event titles/times).
- **Hard rule, not a preference:** email gathering stays server-side, inside
  the Routine, never in the PWA. A public GitHub Pages page requesting a
  broad Gmail scope client-side would mean anyone who ever got hold of a
  leaked token (stolen device, browser extension, XSS in some future feature)
  reads the whole inbox, not just a calendar. Calendar's `calendar.events`
  scope is deliberately narrow for exactly this reason; Gmail scopes aren't
  narrow the same way.
- **Cost:** medium-high. Extending SKILL.md's existing (currently unused)
  email Gather logic to run per-account, merge candidates, and tag each with
  its source inbox so a reader knows which account an ask came from.

### 2d. A non-Google provider (Outlook / Microsoft 365)
- Entirely separate integration: Microsoft Graph API, MSAL.js instead of
  Google Identity Services for any client-side write-back, its own consent
  screen and admin/tenant quirks if it's a work account.
- **Cost:** high. This roughly doubles the calendar-sync code in the PWA
  (two auth libraries, two token lifecycles, two API shapes to normalize into
  one payload schema) and doubles the Gather instructions in the Routine.
- Only worth it if a real, separate Outlook calendar/inbox exists that can't
  be folded into Google by other means (see §4).

## 3. Costs, plainly

| | Money | Time to build | Ongoing burden |
|---|---|---|---|
| 2a. second calendar, same account | $0 | ~30 min | none |
| 2b. second Google account | $0 (Calendar API is free at this scale) | medium (UI + merge logic) | 2x token expiry/reconnect edge cases |
| 2c. multiple inboxes | $0 | medium-high | 2x+ reconnect edge cases, bigger privacy stakes |
| 2d. Outlook/Microsoft | $0 (Graph API free tier covers personal use) | high | a second, unrelated auth system to maintain forever |

There's no recurring dollar cost at personal scale on either Google's or
Microsoft's side — the cost here is entirely engineering time up front and
maintenance (broken tokens, silent partial failures, more surface for bugs)
after.

## 4. The cheaper alternative worth trying first

Before building any of §2b–2d, use the account providers' own consolidation
features — this gets most of the value with none of the new plumbing:

- **Calendars:** in Google Calendar, use "Other calendars → Subscribe" (for
  a calendar you can see) or have the other account share its calendar with
  your primary one. Every subscribed/shared calendar then shows up inside
  the *one* account Day Run already has full access to — no second OAuth
  grant, no account switcher, no merge logic. This covers a second Google
  account and, via ICS subscription, most non-Google calendars too (Outlook
  can publish an ICS feed your Google account can subscribe to — read-only,
  but if you don't need to edit that calendar's events from Day Run, it's
  the entire multi-provider problem solved for free).
- **Inboxes:** Gmail natively supports "Add another mail account you own" and
  delegate access, or plain auto-forwarding from a secondary inbox into the
  primary one. Either consolidates N inboxes into the one Gmail account the
  Routine would gather from — again, zero new auth surface.

This is the recommended first move: it's reversible, costs nothing, and
avoids nearly every weakness in §5 below.

## 5. Weaknesses and risks, independent of which path

- **Connector multiplicity is genuinely unconfirmed.** This session hit a
  hard wall trying to pass connector grants to a routine at all (blocked by
  org policy on the `connectors` parameter). Whether the underlying platform
  even supports two live connections of the same type needs a direct answer
  from claude.ai's connector settings before any of §2b/2c is worth coding.
- **Public page, growing sensitivity.** The repo is public because free
  GitHub Pages requires it. One calendar's worth of event titles/times on a
  public URL is a bounded exposure; email content from multiple inboxes is
  not. If email gathering is added, revisit the privacy tradeoff in the
  README — a private repo (paid plan) or an access gate stops being optional
  once inbox content is what's rendered.
- **Prompt-injection surface scales with source count.** SKILL.md's Ground
  Rules already treat every gathered item as data, never instructions — that
  holds regardless of account count, but more accounts means more untrusted
  text flowing through the same pipeline, so it's worth re-verifying that
  rule stays airtight before fanning out.
- **Silent partial failure.** With N accounts, one expired/revoked token
  shouldn't take down the whole render — the Routine needs to degrade to
  "skip this account, note it's stale" rather than fail the whole build, or
  a broken personal-account grant quietly loses that account's events with
  no visible signal anything's wrong.
- **De-duplication.** The same real-world meeting can appear on more than one
  calendar (an invite that syncs to both a work and a personal calendar) —
  merging sources without double-listing it needs explicit Sort logic that
  doesn't exist today.
- **Token lifecycle multiplies linearly.** Every added account is another
  OAuth grant that can expire, get revoked, or need re-consent — on the PWA
  side that's another "reconnect" button state to design for; on the Routine
  side it's another silent-failure mode to guard against (previous bullet).

## 6. The road, phased

1. **Now, cheap:** try §4's native consolidation first. Likely solves
   "multiple calendars" and "multiple inboxes" for $0 and no new code.
2. **If that's not enough — second calendar, same account (§2a):** small,
   safe, worth doing regardless.
3. **If a truly separate account is unavoidable — confirm connector
   multiplicity** with claude.ai's connector settings before writing code.
   No answer there = stop, this path is blocked upstream, not by Day Run.
4. **Only then — second Google account (§2b), calendar only.** Keep email
   off this path entirely at this stage.
5. **Multiple inboxes (§2c) — last, and reconsider repo privacy first.** The
   payoff (asks/objectives surfaced automatically) is real, but this is
   where the privacy tradeoff in the README stops being casual.
6. **Outlook/Microsoft (§2d) — only if genuinely unavoidable.** Prefer an
   ICS subscription into Google (read-only, zero new auth) over a second
   full auth system, unless write-back to that specific calendar is a hard
   requirement.

## Recommendation

Don't build §2b–2d yet. Try the Google-native consolidation in §4 first — it
answers "can this manage my other inbox/calendar" with a yes, today, for
free, using exactly what's already deployed. Revisit this document if that
turns out to be insufficient (e.g., a non-Google inbox that genuinely can't
be forwarded, or a need to *write* to a second account's calendar
specifically, which subscription/sharing can't do since those are typically
read-only views of someone else's calendar).
