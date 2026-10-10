# WorkSync: what's happening on my road

Local demonstrator for coordinating road works: departments register work, contractors confirm dates, departments approve one exact plan, utilities finish and pass inspection, and **final resurfacing starts only when a server-side gate passes**. Residents (no account needed) see what is happening near their location on a map, see problems reported nearby, report problems and follow them; complaints go only to the right department, duplicates raise priority, and a missed promise escalates to the head of department. **Staff must sign in** to see or change anything internal.

```
worksync/
  root/       specs and contract (WORKSYNC_API_CONTRACT.md + WORKSYNC_API_ADDENDUM.md for sign-in, location and complaints)
  backend/    FastAPI + SQLite  (README.md, DEMO_CREDENTIALS.md, 140 tests)
  frontend/   React + Vite + TypeScript + Leaflet map  (README.md, 27 tests)
  EXAMPLE_PROBLEMS.md   example problems for every category and every situation
  .tools/     project-local Node.js (optional; see below)
  DEPLOY.md, Dockerfile, render.yaml   one public link (website + API from one service)
```

## Quick start

Terminal 1 (backend; see `backend/README.md` for Windows):

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python seed.py --reset
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

Terminal 2 (frontend):

```bash
cd frontend && npm install && cp .env.example .env && npm run dev
```

Open **<http://localhost:5173>** (use `localhost`, not `127.0.0.1`; API docs at <http://localhost:8000/docs>). Staff accounts: `backend/DEMO_CREDENTIALS.md`. Data lives in `backend/worksync.db`; `seed.py --reset` restores the starting state: **no streets or works**. As the coordinator (`admin`) press "Create sample works and complaints here" on the Projects page to try it around a place you choose; it creates example complaints for every situation (see `EXAMPLE_PROBLEMS.md`).

If Node is not installed system-wide, this folder contains a project-local copy in `.tools/node` (Node 24 LTS, checksum-verified). Use it without installing anything:

```bash
export PATH="$PWD/.tools/node/bin:$PATH"
```

## Hosting it (public link)

See **[DEPLOY.md](DEPLOY.md)**: the backend also serves the built website, so one Render service is the whole site. Settings are environment variables (staff password, sample data, database path).

## What was verified

- **Backend:** 140 automated tests pass, run through real sign-in. New in this version: routing (an electrical complaint is visible only to Power, its head and the coordinator; other departments get 404, contractors and inspectors 403), duplicate grouping by category and distance, priority at 2+ and 4+ reports, promised dates and escalation (missed promise -> head, HIGH; missed again or head silent 2 days -> coordinator, URGENT; resolved in time -> never), the resident confirming or reopening, the public feed leaking nothing personal, streets registered on demand and reused, the opt-in sample scenario, a clean install with no streets, and optional Google sign-in with a *mocked* Google (wrong audience/issuer/expiry/unverified e-mail refused, resident tokens cannot open any staff endpoint and vice versa). Earlier tests (schedule, gate, permissions, idempotency, persistence, audit) still pass.
- **Frontend:** `tsc` clean, production build OK, 27 tests pass.
- **Staff window and resident accounts (backend tests):** the overview is scoped to a department (staff cannot widen it); only a head or the coordinator can open the team view; a head sees every colleague's workload, resolution times and actions while other staff see only their own; assignment rules (staff may take work for themselves, only a head or the coordinator gives it to someone else, wrong-department and stale-version requests are refused); staff names never reach residents; history search, filters and pagination never cross departments; project history is visible only to people who may see the project; CSV export is scoped and neutralises spreadsheet formulas; resident accounts store only salted hashes, refuse weak passwords, treat a wrong password and an unknown e-mail identically, lock after repeated failures, rate-limit sign-ups, can claim a guest report with its code, and are never merged with a Google account.
- **Staff window and resident accounts (in the browser):** the Water head's Overview and Team views with each colleague's open complaints, projects, closed work and actions; History search finding a past complaint with who handled it and how long it took; the head's Complaints screen showing who handles each problem with the "give it to" list; creating a resident account (a weak password refused with reasons, then success), and adding a report remembered on the device to the account so it appears under "My reports".
- **Not clicked through in the browser:** assigning a complaint or project to someone, the History project tab and a project's history trail, the CSV download buttons, the coordinator's Overview/Teams, and changing a resident's password (all covered by the backend tests).
- **In the browser against the real backend (OpenStreetMap map and search included):** a fresh install showing no streets; the coordinator creating sample works around a searched place; the home map framing the area with the "You" marker and road-works pins; the nearby list and the "Public grievances near you" box; a guest reporting an electrical fault (routed to Power, remembered on the device); four reports (three filed through the API, one through the form) becoming one URGENT problem in Power's inbox, with Water seeing nothing (checked through the API); a department promising 5 days through the form; the simulated calendar moved past it through the API and the problem escalating to the head (ordinary staff refused and the head allowed, checked through the API); the resident seeing the escalation, promise and full timeline with new-update counts; the head resolving it (through the API) and the resident confirming it is fixed in the browser.

## Decisions and limits worth knowing

See "Where the contract was silent" and "Known limits" in `backend/README.md`. In short: a start needs the demo date to equal the approved date; late finishes and post-start changes create a review hold with no override; replanning after work starts is unsupported; the demo clock is simulated and forward-only. All buffers and the 180-day windows are labelled demo policy. The system checks known registered work and cannot physically prevent unregistered excavation.

Not verified: **real Google sign-in** (it needs your Google client id and account, so only the server side with a mocked Google was tested; the button was never shown to a real Google), notifications by e-mail or SMS (not implemented: they need an outside provider), the "I'm seeing this too" button and the escalation to the *coordinator* level in the browser (both covered by the backend tests), behaviour on Windows (commands are provided but untested), the browser's location success path (the preview browser denied the permission, so only the denied-permission message and the typed-place route were exercised; the code for a granted position is covered only by reading it and by the distance tests), multi-user concurrent load beyond the race test, and screen-reader testing. Sign-in is a demonstration mechanism, not production authentication: no password reset, no multi-factor, and sessions are not bound to a device.
