# WorkSync backend

Local demonstrator backend for road-work coordination: FastAPI + Pydantic + SQLite (`sqlite3`). No maps, LLMs, uploads or cloud services in the backend. **Staff must sign in** (username + password, Bearer session token); the public needs no sign-in and sees only public endpoints. This is a demonstration mechanism, **not** production authentication.

Interface: `../root/WORKSYNC_API_CONTRACT.md` as amended by `../root/WORKSYNC_API_ADDENDUM.md` (sign-in replaces the `X-Demo-User` header; public roads and complaints were added). All 20 original endpoints are implemented, plus the addendum's.

## Run it

Python 3.9+ (developed and tested on 3.9.6).

**macOS / Linux**

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python seed.py --reset                         # creates worksync.db: users and clock only, no streets or works
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

**Windows (PowerShell)**

```powershell
cd backend
py -3 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python seed.py --reset
.venv\Scripts\uvicorn main:app --host 127.0.0.1 --port 8000
```

- Interactive docs: <http://localhost:8000/docs> · schema: <http://localhost:8000/openapi.json>
- If the database file is empty the server seeds it on first start (`WORKSYNC_AUTOSEED=0` disables this). A database made by an older version (before sign-in) is refused with a clear message: run `seed.py --reset`.
- Run the tests: `.venv/bin/python -m pytest tests -q` (Windows: `.venv\Scripts\python -m pytest tests -q`). 130 tests.

Configuration (environment variables):

| Variable | Default | Meaning |
|---|---|---|
| `WORKSYNC_DB` | `backend/worksync.db` | SQLite file |
| `WORKSYNC_CORS_ORIGINS` | `http://localhost:5173` | Comma-separated allowed origins (exact match, never `*`) |
| `WORKSYNC_AUTOSEED` | `1` | Seed an empty database on start |
| `WORKSYNC_ALLOW_REMOTE_CLOCK` | unset | Allow the demo clock from non-local clients |
| `WORKSYNC_GOOGLE_CLIENT_ID` | unset | Turns on optional Google sign-in for residents (see below) |

## Sign-in (staff) and the public

Staff sign in with `POST /api/v1/auth/login` and send `Authorization: Bearer <token>`. The dummy usernames and passwords are in **[DEMO_CREDENTIALS.md](DEMO_CREDENTIALS.md)** (fifteen accounts: four departments, four department heads, four contractors, two inspectors, one coordinator). In `/docs`, call `POST /auth/login`, copy the `token`, press **Authorize** and paste it.

- Passwords are stored as salted PBKDF2-SHA256 hashes; session tokens are stored only as hashes and last 8 hours.
- Wrong password and unknown user get the same answer and take the same time. Five failures for one username from one client lock that pair for five minutes.
- The old `X-Demo-User` header no longer works. Every internal endpoint answers 401 without a valid token (tested for every route).
- The public needs no account: `GET /roads`, `GET /roads/{id}/public`, `GET /bootstrap` (roads, clock, policy only), `POST /complaints` and `POST /complaints/track`.

A fresh database contains **organisations, users and the demo clock (8 Nov 2026) only: no streets, works or complaints.** Departments register
work at a place (`POST /roads`, then `POST /projects`). To try the app, the coordinator can press "Create sample works here" (or call
`POST /demo/scenario {lat, lng}`; CLI: `python seed.py --reset --scenario LAT LNG`), which builds clearly invented sample works around that
point: Market Road (Water 8-12, Telecom 14-17, Surface 21-24 Nov; Power's declaration missing on purpose), Temple Street (no valid
sequential plan) and an empty Station Road, plus 18 example complaints covering every situation, six older complaints handled by different staff with different resolution times, and an older street with two completed projects and one cancelled (new, four duplicates, acknowledged, on track, promise missed and escalated to the head, escalated twice to the coordinator, resolved, reopened, confirmed fixed, closed, and one for each category the coordinator must route). See `../EXAMPLE_PROBLEMS.md`. It can be created once; a reset removes it.

## Five-minute walkthrough with `/docs` or curl

The walkthrough uses the sample scenario: first run `python seed.py --reset --scenario 13.0617 80.2693` (or press "Create sample works here" in the app as the coordinator). Skip this if you register your own works.

Sign in first (`POST /auth/login`) for each role you use. Every POST/PATCH (except sign-in and complaint tracking) needs an `Idempotency-Key` header and (where it changes an existing subject) the current `expected_version`; consent calls also need `plan_version`.

1. `GET /api/v1/cases/case-market` as `admin` → note `version` and `plan_version`.
2. `POST /cases/case-market/responses` as `aqua.contractor`, `u-link`, `u-pave` (`ACCEPT` for `water-1`, `telecom-1`, `surface-1`; re-read `version` each time).
3. `POST /cases/case-market/approvals` as `water.dept`, `u-telecom`, `u-roads` → status `APPROVED`.
4. `GET /projects/surface-1/gate` as `pave.contractor` → eligible `false` with each blocker, the responsible organisation and next action.
5. `POST /projects/water-1/start` as `aqua.contractor` (8 Nov). Then `POST /demo/clock/advance` as `admin` (+4 → 12 Nov), `POST /projects/water-1/finish` (`testing_complete` and `reinstatement_complete` true). Telecom: advance +2 (14 Nov) start, +3 (17 Nov) finish.
6. Advance +3 (20 Nov): `POST /projects/{id}/inspections` as `inspector.nisha` with `UTILITY_RELEASE`/`PASS` for both. Advance +1 (21 Nov).
7. `POST /projects/surface-1/start` as `pave.contractor` → 422 `GATE_BLOCKED` (Power has not confirmed).
8. `POST /roads/road-market/declarations` as `power.dept` (`NO_PLANNED_WORK`) then start surface-1 again → 200 with `pcc_number`.
9. `finish` surface-1, then `FINAL_SURFACE`/`PASS` as `inspector.nisha` → case `COMPLETED`.

## Public features: location, grievances and complaints

Full detail is in `../root/WORKSYNC_API_ADDENDUM.md`. In short:

- **Location.** `GET /roads` returns roads with coordinates and `GET /complaints/public` returns problems with approximate positions; the browser
  computes distances, so a resident's position never reaches this server.
- **Routing.** A complaint's category decides its department (electrical -> Power, water -> Water, telecom -> Telecom, road damage -> Roads;
  the rest go to the coordinator). Only that department, its head and the coordinator can see or act on it; other departments get 404, contractors and
  inspectors 403.
- **Duplicates and priority.** Open reports of the same category within 150 m group into one problem; 2+ reports are `HIGH`, 4+ `URGENT`. The coordinator's
  inbox is sorted most-urgent first.
- **Promise and escalation.** "We will resolve this in N days" fixes a promised date (simulated calendar). Missing it escalates to the head of department
  with `HIGH` priority; a missed second promise (or two days of head silence) escalates to the coordinator as `URGENT`. Checked on every command, by the
  periodic task and on clock advance.
- **Timeline = notifications.** Every change is a plain-language entry the resident sees; the app polls for them. No e-mail/SMS (needs an outside provider).
- **Resident confirms or reopens** after a department marks it resolved (with the tracking code or as a signed-in resident).
- **Privacy.** Reporter positions are rounded to ~100 m, client addresses are stored only as a one-way hash, contact details are visible to the responsible
  staff only, the public feed and the tracking view never include descriptions, contacts, references or codes, and guessing tracking codes is throttled.

### The staff window

Beyond handling one task at a time, staff have: an **overview** (department numbers, what needs attention, my own work), a **team** view for the head of department
(every colleague, what each is working on, workload, resolution times, and the activity trail), **assignment** (a head gives complaints and projects to people; staff
can take work for themselves; whoever first acts on a complaint becomes its handler), a searchable **history** of past complaints and projects with who handled them and
how long they took, a **project history** trail, and **CSV export**. The coordinator sees all departments; ordinary staff see department numbers but only their own
work and actions. Details: `../root/WORKSYNC_API_ADDENDUM.md` sections 8 and 9.

### Resident accounts

Residents may be guests, may create a local account (e-mail + password, stored only as a salted PBKDF2 hash; the e-mail is not verified and nothing is ever sent, so
there is no password-reset e-mail), or may sign in with Google. A report made as a guest can be added to an account with its tracking code.

### Optional Google sign-in

Residents are guests by default. To enable Google sign-in: create an OAuth 2.0 *Web application* client in Google Cloud Console, add `http://localhost:5173` as
an authorised JavaScript origin, and start the backend with `WORKSYNC_GOOGLE_CLIENT_ID=<your client id>.apps.googleusercontent.com`. The button then appears
in the app. The server verifies the Google ID token (audience, issuer, expiry, verified e-mail) via Google's `tokeninfo` endpoint. A Google session is a
*resident* session: it works only for "My reports" and for acting on the resident's own complaints, never on staff endpoints.

## What the backend decides (and the frontend must not)

- **Permissions** come from the seeded user's role/organisation and the resource's ownership/assignment; `allowed_actions` is computed on the server, never trusted from the client.
- **Scheduler** (`scheduler.py`, pure): inclusive dates; utility start = max(earliest start, previous utility finish + 2 days); surface start = max(earliest start, last utility finish + 4 days); every hard deadline is checked; all orderings of ≤3 utilities are tried; earliest final completion wins with stable id tie-breaking. Outcomes `PLAN_FOUND` / `NO_SEQUENTIAL_PLAN` (with the violated constraints, never a claim of global impossibility) / `UNASSESSABLE` (missing dates or unsupported size; nothing is silently dropped).
- **Versions**: `version` is a row counter; `material_version` changes with planning edits; `plan_version` identifies an immutable plan (rows are protected by triggers); road `registry_version` changes only when registered planning scope changes, and declarations bind to it.
- **Consent**: contractors respond per project and per plan version; all owning departments must approve that exact version. Any material edit before execution returns the case to `DRAFT` and old consent no longer counts (history is kept). 48-hour review deadlines block (never approve) overdue cases.
- **Gate** (`compute_gate`, a pure read, shared by `GET …/gate` and `POST …/start`): approved current plan with complete consent, no hold, no new relevant project, start date equals the approved date, earlier utilities done with separation; for resurfacing additionally every utility finished with testing/reinstatement declared, release inspection PASS at least 3 days after finish, surfacing at least 1 day after inspection and 4 days after the last finish, and a current registry-bound declaration from every expected utility department covering the review horizon. Checks that do not depend on the plan's dates run even when no plan exists, so a missing plan never reads as a pass.
- **Transactions**: every mutation is one `BEGIN IMMEDIATE` transaction containing the change, the append-only audit row and the idempotency record. Order inside the transaction: access → idempotency replay → expected versions → business rules.
- **Idempotency**: key + user + action + payload hash. Same → the stored original response (header `Idempotent-Replay: true`); same key with different payload → 409 `IDEMPOTENCY_MISMATCH`. Refused attempts are not stored, so a corrected retry is evaluated afresh.

## Where the contract was silent (decisions)

- Creating a project attaches it to the road's single active case (creating `DRAFT` if needed). `POST …/plans` generates the plan: `PLAN_FOUND` → `CONTRACTOR_REVIEW` (48 h), otherwise `BLOCKED` with the saved assessment.
- Counter-proposing a later earliest start updates the project, creates a new plan version, and needs fresh responses from everyone.
- A start is allowed only when the demo date **equals** the approved start; a later date needs an administrator review (no override exists).
- Late finishing (after the planned end) requires `delay_reason` and places a review hold; replanning after work has started is unsupported (422 `REPLAN_UNSUPPORTED`), as are edits/cancellation of started work (409 `WORK_STARTED`).
- Release inspections are accepted only from 3 days after the finish date (422 `INSPECTION_TOO_EARLY`). A later PASS supersedes an earlier FAIL.
- Incident holds clear only through an administrator's `REQUEST_REVISION` on a case with no started work (the reports are then marked reviewed; nothing is authorised).
- Review horizon anchor: resurfacing deadline + 180 days. Work starting after it is shown with an exclusion reason and is not part of the plan.
- Bootstrap response keys: `roads`, `clock` (`date`, `version`), `policy`, `complaint_categories`, and, when signed in, `contractors`, `departments`, `current_user`, `allowed_actions`. There is no public list of staff. Mutation results always include `id`, `version`, `case_id`, `message`, `recorded_at` plus action-specific extras. Only `POST /projects` returns 201; other actions return 200.

## Known limits (demo scope)

No parallel work, waivers, emergency works, real authentication, GIS, or notifications. Demo clock only moves forward by explicit request. The periodic deadline checker and command-time checks both use the simulated clock, so time-outs happen when the clock is advanced.

## Files

`main.py` routes/CORS/errors · `schemas.py` request and response models · `db.py` schema, triggers, transactions · `auth.py` demo identity · `errors.py` error envelope · `scheduler.py` pure date maths · `service.py` workflow, gate, mutations, audit · `views.py` read models and `allowed_actions` · `complaints.py` routing, duplicates, priority, escalation, timeline · `google.py` token verification · `seed.py` users, dummy credentials and the opt-in sample scenario · `DEMO_CREDENTIALS.md` · `tests/` (130 tests).
