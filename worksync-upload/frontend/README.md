# WorkSync frontend

React 18 + Vite + TypeScript. Four screens (My road · Projects · Coordinate work · Work and checks). All state shown comes from the backend; no scheduling, permission or start-eligibility rules exist here.

## Run it

Requires Node.js 18+ (the project was built with Node 24 LTS) and the backend running on <http://localhost:8000> (see `../backend/README.md`).

```bash
cd frontend
npm install
cp .env.example .env        # Windows PowerShell: Copy-Item .env.example .env
npm run dev                 # http://localhost:5173
```

Open **<http://localhost:5173>** (use `localhost`, not `127.0.0.1`: the backend's CORS allows exactly `http://localhost:5173`).

Other commands: `npm run build` (typecheck + production build), `npm run typecheck`, `npm test` (27 tests: api client, credential separation, location helpers, on-device reports).

`VITE_API_BASE_URL` (default `http://localhost:8000`) points at the backend. The API lives under `/api/v1`.

## Using it

**Public (no account).** The home page uses your location: press **Use my current location** (the browser asks; if it was already allowed it is used
automatically) or search for a place. You see a **map** with your position, nearby **road works** and **reported problems**, a list of road works near
you, and the **Public grievances near you** box (what people nearby have reported, how many reports, status, any promised date and whether it was escalated;
"I'm seeing this too" starts a report at that spot). **Report a problem** picks the category (and tells you which department it goes to), your location on a map,
and optional contact details; you get a reference and a private tracking code. **Track a complaint** shows the detailed status with the full timeline, the
promised date, any escalation and how many people reported the same problem. **My reports** lists your reports (remembered on this device, or in your Google
account) with a count of new updates, and lets you confirm a fix or reopen. The app checks for updates every 30 seconds and shows a notice when something changes.

**Accounts are optional.** *Sign in / Create account* (top right) offers a local account (e-mail and password; stored only as a salted hash, no verification e-mail is ever sent) and, if the backend has `WORKSYNC_GOOGLE_CLIENT_ID`, Google. Everyone else is a guest. From the account page you can add reports remembered on this device to your account, and change your password.

**Staff.** Press **Staff sign in** and use an account from `../backend/DEMO_CREDENTIALS.md`. The staff workspace appears only after the server accepts the sign-in: **Overview** (department numbers, what needs attention, my work), Projects, Coordinate work, Work and checks, **Complaints** (open problems, with who is handling each and assignment), **History** (searchable past complaints and projects, with CSV download) and, for a head of department, **My team** (every colleague, what each is working on, and the activity trail). The coordinator's **Teams** tab covers every department. Departments register work at a place: choose an existing
street or "A new place on the map…". The **Complaints** inbox shows only your department's problems (the coordinator sees all), most urgent first, with the
reason for the priority, the reports (with contact details), the status history, a promise ("we will resolve this within N days") and, for the coordinator, routing.
A fresh install has no streets: as the coordinator, press **Create sample works and complaints here** on the Projects page to try everything around a place you choose; the example complaints and their tracking codes are listed once. The report form also offers "For example" lines for each category.

Privacy: a resident's position stays in the browser (distances are computed there). Typed place names go to OpenStreetMap Nominatim, the map picture loads from
OpenStreetMap, and the Google script loads only if Google sign-in is configured. A report can attach a position rounded to about 100 m.

## How it maps to the contract

| Part | Where |
|---|---|
| One HTTP client, `VITE_API_BASE_URL`, Bearer session token, `Idempotency-Key` | `src/api.ts` |
| Idempotency keys | Same action + same payload after a network failure reuses its key; a new or changed action gets a new key; keys are forgotten once the server answers |
| Versions | Read from the latest server response and sent back as `expected_version` / `plan_version`; treated as opaque |
| Errors | The shared envelope becomes `ApiRequestError`; field failures show beside fields; stale errors show "This plan changed. Refresh to review the latest dates." with a Refresh button and never resubmit |
| Buttons | Shown only when the server's `allowed_actions` lists them |
| Components | `StatusBadge`, `DateLabel`, `ProjectCard`, `ScheduleList`, `ActionPanel`, `GateChecklist`, `EmptyState` (+ `Notice`, `Field`, `Stepper`) in `src/components` |

Proposed, confirmed, actual and verified dates use four distinct labels and styles; a proposed date is never presented as a promise. Plan approval and start eligibility are shown separately.

## Notes

- Stored in the browser (all optional): the staff session token and any resident session token in `sessionStorage` (this tab only); the selected staff street in `localStorage`; and reports a guest chose to remember on this device (reference + tracking code) in `localStorage`, which they can forget at any time. A resident's location is never stored.
- The map is Leaflet (installed from npm) with OpenStreetMap tiles.
- Accessibility: visible labels and focus, ≥44 px controls, text + icon with every status colour, `aria-live` feedback.
- No analytics or tracking. Third-party requests: OpenStreetMap map tiles and, when a place is typed, Nominatim search; Google's script only if sign-in is configured. Browser geolocation runs only when the person presses the button (or has already allowed it).
