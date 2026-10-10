# WorkSync: what's happening on my road

**Live app:** `https://tesseract-l8pq.onrender.com`  (open it, nothing to install)
**Demo video:** `demo.mp4` in this repository, or `PASTE-VIDEO-LINK-HERE`

WorkSync is a web app for coordinating road works and for letting residents see and report what is happening near them.

- **Departments** register road works. **Contractors** confirm dates. Each **department approves one exact plan.**
  **Utilities** finish and pass inspection before the final resurfacing, and a **server-side gate** decides whether work
  may start, so the screen cannot override it.
- **Residents need no account.** They see road works and reported problems near their location on a map, report
  problems (to the right department only), track them with a private code, and confirm a fix or reopen it. Duplicate
  reports raise priority. A missed promise escalates to the head of department, then the coordinator.
- **Staff must sign in.** Each department sees only its own complaints. Heads see their team and its workload; the
  coordinator sees everything.

## For judges: try it in two minutes

1. Open the live link. On the home page search **`Anna Nagar Chennai`** and choose the first result. The sample works
   and problems are in Chennai, and the page shows what is within 10 km of the place you choose.
2. Press **Report a problem**, choose a category, tap an example, pin a place or search for one, and send. Keep the
   reference and tracking code, then use **Track a complaint** or **My reports**.
3. Press **Staff sign in** and use any username below with the **staff password given in the submission**
   (the same password for every account on the hosted site):

| Username | Who | Good for seeing |
|---|---|---|
| `admin` | Coordinator | everything: all departments, teams, sample-data button |
| `roads.dept` | Roads department staff | complaints routed to Roads; acknowledge, promise N days, resolve |
| `water.head` | Head of Water | team oversight, escalated complaints, history |
| `aqua.contractor` | Contractor | answering proposed dates |
| `inspector.nisha` | Inspector | recording inspections |

All usernames are in `backend/DEMO_CREDENTIALS.md`. The data and the people are fictional.

> The demo clock is simulated and closed on the public site, because it is shared by every visitor and only moves
> forward. The sample data already contains an escalated complaint so escalation can be seen.

## How it is built

```
worksync/
  root/       the specification files (API contract, addendum, frontend brief)
  backend/    FastAPI + SQLite   (README.md, DEMO_CREDENTIALS.md, 140 tests)
  frontend/   React + Vite + TypeScript + Leaflet map   (README.md, 27 tests)
  Dockerfile, render.yaml, DEPLOY.md   one public link (website and API from one service)
  EXAMPLE_PROBLEMS.md   example problems for every category and situation
```

- **Backend:** all rules live here. A scheduler builds the plan (inclusive dates, a gap between utility work and
  resurfacing); a state machine moves each case through contractor and department review; a gate (`compute_gate`)
  decides whether work may start. Writes use transactions, optimistic version checks and idempotency keys; the audit
  trail is append-only and approved plans are immutable (enforced by database triggers).
- **Frontend:** shows only what the server allows (`allowed_actions`). The map is Leaflet with OpenStreetMap; place
  search uses OpenStreetMap's Nominatim; the browser's location stays in the browser and is never sent to the server.
- **Privacy and safety:** positions are rounded to about 100 m; contact details are visible only to staff; passwords
  are salted PBKDF2-SHA256 hashes; session tokens are stored hashed; failed sign-ins and tracking-code guesses are
  throttled; resident sessions can never open staff endpoints.
- **Residents** can be guests (a tracking code, remembered on the device if they choose), create a local account
  (e-mail and password), or use Google sign-in when configured. None is required.

## Run it on your own computer

Terminal 1 (backend; see `backend/README.md` for Windows):

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python seed.py --reset --scenario 13.0617 80.2693      # with sample data around Chennai
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

Terminal 2 (frontend):

```bash
cd frontend && npm install && cp .env.example .env && npm run dev
```

Open **http://localhost:5173** (use `localhost`, not `127.0.0.1`). API documentation: http://localhost:8000/docs.
Local staff passwords are in `backend/DEMO_CREDENTIALS.md`. Without `--scenario` a fresh install starts empty, and
the coordinator can create the sample data from the Projects page.

Tests: `cd backend && .venv/bin/python -m pytest` (140) and `cd frontend && npm test` (27).

## Hosting

The backend also serves the built website, so one service is the whole site. See **[DEPLOY.md](DEPLOY.md)** for the
Render steps, the environment variables (staff password, sample data, database path) and the free-plan caveats.

## What was verified

- **Backend (automated, 140 tests):** schedule and gate rules, permissions per role, complaint routing (an electrical
  complaint is visible only to Power, its head and the coordinator), duplicate grouping and priority, promised dates
  and escalation, residents confirming or reopening, the public feed leaking nothing personal, staff overview, team
  oversight and history scoping, CSV export neutralising spreadsheet formulas, resident accounts (salted hashes, weak
  passwords refused, lockout after repeated failures), idempotency, persistence, audit, and hosting (one address,
  staff password and sample data set at deploy time, clock closed behind a proxy).
- **Frontend (automated, 27 tests)** and a clean type check and production build.
- **In a browser against the real backend:** a fresh install; sample works around a searched place; the map, nearby
  list and "Public grievances near you"; a guest reporting a problem and tracking it; duplicate reports becoming one
  urgent problem; a department promising a number of days; escalation to the head; the resident confirming a fix;
  creating a resident account; the head's team and history views; and the production build served from one address.

## Not verified, and known limits

- **Real Google sign-in** was not tested with Google (only the server side with a mocked Google).
- **The Docker image and the Render deployment** were prepared but not run on the machine they were written on.
- **Browser location** (the GPS "Use my current location" success path) was not exercised; the typed-place route and
  the permission-denied message were.
- **Not clicked through in a browser** (covered by backend tests): assigning work to a colleague with the buttons, the
  History projects tab and project trail, CSV download buttons, the coordinator's Teams view, changing a password.
- **E-mail and SMS notifications are not implemented.** Residents are notified inside the app, and the app checks
  for updates every 30 seconds.
- **Languages:** English only. Tamil, Hindi and Telugu are planned, not built.
- **It is a demonstrator, not production software.** One shared staff password on the hosted site, no password
  reset or multi-factor, one SQLite file, and a simulated forward-only clock. The system checks known registered
  work; it cannot physically prevent unregistered excavation. A start needs the demo date to equal the approved date;
  late finishes and changes after a start create a review hold; replanning after work starts is unsupported. All
  buffers and the 180-day windows are labelled demo policy. See "Known limits" in `backend/README.md`.
