# WorkSync API addendum

This addendum **supersedes** parts of `WORKSYNC_API_CONTRACT.md`. Everything not mentioned here is unchanged. It covers:
sign-in, locations instead of fixed streets, the public grievance feed, and complaints (routing, priority, promises,
escalation, timeline, resident responses, optional Google sign-in).

## 1. Connection rules

- `X-Demo-User` is **removed**. Staff sign in with `POST /api/v1/auth/login` and send `Authorization: Bearer <token>`.
- Residents never need to sign in. They may optionally sign in with Google (`POST /auth/google`); that gives a *resident*
  token (`Authorization: Bearer <resident token>`) which works only on resident and public endpoints, never on staff
  endpoints. A staff token is likewise not a resident.
- CORS allows `Content-Type`, `Authorization` and `Idempotency-Key` from the configured frontend origin (default exactly
  `http://localhost:5173`).
- New error codes: `401 INVALID_CREDENTIALS`, `404` for a complaint a department may not see (it cannot tell it exists),
  `429 TOO_MANY_ATTEMPTS`, `429 TOO_MANY_COMPLAINTS`, `503 GOOGLE_NOT_CONFIGURED` / `GOOGLE_UNAVAILABLE`.

## 2. Public vs staff

| Access | Endpoints |
|---|---|
| **Public, no credentials** | `GET /bootstrap` (roads with coordinates, clock, policy, complaint categories, Google client id), `GET /roads`, `GET /roads/{id}/public`, `GET /complaints/public`, `POST /complaints`, `POST /complaints/track`, `POST /complaints/respond` |
| **Resident (optional Google)** | `POST /auth/google`, `GET /auth/resident/me`, `POST /auth/resident/logout`, `GET /me/complaints`; also recognised on `POST /complaints`, `/complaints/track`, `/complaints/respond` |
| **Staff, Bearer token** | everything else in the contract, plus `GET /auth/me`, `POST /auth/logout`, `GET /complaints`, `POST /complaints/{id}/status`, `POST /complaints/{id}/assign`, `POST /roads`, `POST /demo/scenario` |

The public bootstrap lists no staff. With a staff token it also returns `contractors`, `departments`, `current_user`
(`is_head` for department heads) and global `allowed_actions`.

## 3. Places instead of fixed streets

A fresh install has **no streets, works or complaints**. Departments register work at a place.

| Method / path | Access | Notes |
|---|---|---|
| `POST /roads` | Department, Admin | `{name, lat, lng, area_label?}` -> 201 `{id, name, created}`. A street with the same name within 150 m is reused (`created:false`). Every utility department is expected to confirm its work on the new street. |
| `GET /roads` | Public | `[{id, name, lat, lng, area_label, work_count, in_progress_count, notices[], works[]}]`. Distances are computed in the browser, so a resident's position is never sent to the server. |
| `POST /demo/scenario` | Admin | `{lat, lng}` -> creates clearly invented sample works around that point, **once** (409 `SCENARIO_EXISTS` after). Reset with `seed.py --reset`. CLI: `python seed.py --reset --scenario LAT LNG`. |

## 4. Complaints

### Routing and who can see them

`category` decides the receiving department: `WATER` -> Water, `ELECTRICAL` -> Power, `TELECOM` -> Telecom,
`ROAD_DAMAGE` -> Roads. `SAFETY_HAZARD`, `WORK_WITHOUT_NOTICE`, `DELAY`, `NOISE_DUST`, `OTHER` go to the coordinator
(admin), who assigns them with `POST /complaints/{id}/assign {expected_version, department_id}`.

A department's staff, its head and the coordinator can see a complaint. Everyone else gets `403` (contractors,
inspectors) or `404` (other departments).

### Duplicates and priority

Open reports of the same `category` within 150 m (or on the same street when no position is known) form one *problem*.
Priority is computed on the server: 2+ reports `HIGH`, 4+ `URGENT`, a safety hazard at least `HIGH`, a reopened
complaint at least `HIGH`, escalation to the head `HIGH`, escalation to the coordinator `URGENT`. Staff act on the whole
problem; every reporter gets the update. `GET /complaints` returns one item per problem, most urgent first.

### Promises and escalation

A department sets `IN_PROGRESS` with `resolve_in_days` (1-60): the promised date is *simulated-calendar date + N*. If the
date passes without `RESOLVED`: escalation level 1, the head of department gets it (only the head or coordinator can then act,
and only they can set a new promise), priority at least `HIGH`. If the head's new promise is missed, or the head does nothing
for 2 days: level 2, the coordinator, `URGENT`. Checked on every command, by the periodic task, and when the clock advances.

### Statuses and the resident's part

`NEW` -> `ACKNOWLEDGED` -> `IN_PROGRESS` -> `RESOLVED`; staff may also `REJECTED`. After `RESOLVED` the person who
complained answers with `POST /complaints/respond {reference, action: CONFIRM_FIXED|REOPEN, code?, note?}` (the tracking
code, or a signed-in resident who owns it) -> `CONFIRMED_FIXED` or `REOPENED` (reopening returns it to the department
with raised priority; everyone in the group is told).

### Timeline = notifications

Every change adds a plain-language entry (`GET`-able through `POST /complaints/track` and `GET /me/complaints`), e.g. "The
Power Department will resolve this within 5 days, by 13 Nov 2026." The app polls and shows new entries; e-mail/SMS would
need an outside provider and are not implemented.

### Endpoints

| Method / path | Access | Notes |
|---|---|---|
| `POST /complaints` | Public | `{category, description (10-1000), road_id?, location_text?, lat?, lng?, contact_name?, contact_detail?}` + `Idempotency-Key` -> 201 `{id, tracking_code, department_name, other_reports, priority, status, message}`. Position rounded to ~100 m; 5 reports / 10 min per client. |
| `POST /complaints/track` | Public/resident | `{reference, code}` -> status, priority, department, promise date, escalation, group size, `can_respond`, `timeline[]`. Never the description or contact details. Wrong guesses are throttled. |
| `POST /complaints/respond` | Public/resident | see above |
| `GET /complaints/public` | Public | Approximate problems near people: category, status, priority, report count, since, promised date, escalation flag, approximate position. No description, contact, reference or code. |
| `GET /complaints?status=&priority=` | Department, Admin | Grouped problems with `reports[]` (incl. contact details), `timeline[]`, `due_on`, `days_left`, `overdue`, `escalation_level`, `next_statuses[]`, `allowed_actions` |
| `POST /complaints/{id}/status` | Department, Admin | `{expected_version, status: ACKNOWLEDGED\|IN_PROGRESS\|RESOLVED\|REJECTED, note?, resolve_in_days?}`; a note is required for RESOLVED/REJECTED and is shown to the people who reported it |
| `POST /complaints/{id}/assign` | Admin | route to a department |
| `GET /me/complaints` | Resident | the signed-in resident's own reports |

`allowed_actions` gains `VIEW_COMPLAINTS`, `TRIAGE_COMPLAINT`, `ASSIGN_COMPLAINT`, `CREATE_SCENARIO`.

## 5. Staff sign-in and sessions

`POST /auth/login {username, password}` -> `{token, expires_at, user}` (`user.is_head` for department heads). Passwords are
salted PBKDF2-SHA256; tokens are stored only as hashes and last 8 hours. Five failed attempts for one username from one
client lock that pair for five minutes. Dummy accounts: `backend/DEMO_CREDENTIALS.md`. This is a demonstration mechanism, not
production authentication.

## 6. Optional Google sign-in (residents)

Enabled only when the server has `WORKSYNC_GOOGLE_CLIENT_ID` (an OAuth 2.0 *Web* client id you create in Google Cloud
Console, with `http://localhost:5173` as an authorised JavaScript origin). The browser gets a Google ID token (Google
Identity Services) and posts it to `POST /auth/google`; the server verifies audience, issuer, expiry and e-mail
verification through Google's `tokeninfo` endpoint. Guests are unaffected. Google's script is loaded only when the id is configured.

## 7. External services (all browser-side, all optional to the core flows)

| Service | When | What it learns |
|---|---|---|
| Browser geolocation | only after a button press (or if already permitted) | stays in the browser |
| OpenStreetMap Nominatim search | when a place name is typed | the typed text |
| OpenStreetMap map tiles (`tile.openstreetmap.org`) | whenever a map is shown | roughly which area is viewed |
| Google Identity Services | only if a client id is configured | that a Google sign-in was offered |


## 8. The staff window: overview, team, history, assignment (added later)

| Method / path | Access | Notes |
|---|---|---|
| `GET /overview?department_id=` | Department, Admin | Counts (open, urgent, overdue, escalated, unassigned, awaiting confirmation, reopened, closed, average days to resolve), by-category table, project counts, a "needs attention" list, "my work" and recent activity. A department user always gets their own department; only the coordinator can choose another or all. |
| `GET /team?department_id=` | Head of department, Admin | Every colleague with open complaints, overdue/escalated, resolved total and average days, active/completed projects, action count and last activity. Ordinary staff get 403. |
| `GET /team/{user_id}` | The person, their head, Admin | That person's open and closed complaints, projects and recent actions. |
| `GET /activity?limit&offset&user_id&department_id` | Department, Admin | The activity trail. Heads and the coordinator see everyone in scope; other staff see only their own actions. Sign-ins are not shown. |
| `GET /complaints?scope=open\|closed\|all&q&category&assigned&status&priority&opened_from&opened_to&limit&offset` | Department, Admin | Search, filter and paginate (`{items, total}`). `scope=closed` is the History archive. `q` needs every word to match (references, descriptions, street, handler). |
| `POST /complaints/{id}/assign-staff` | Head, Admin; staff for themselves | `{expected_version, user_id}`; `null` removes the assignment (heads only). The person who first works on an unassigned complaint becomes its handler. Residents are told only that "a member of the team" has it; staff names never reach them. |
| `GET /projects?state=active\|done\|cancelled\|past&q=` | as before | Project history and search. Each project now has `lead_user_id`/`lead_name`, `created_by_name`, `cancel_reason`. |
| `GET /projects/{id}/history` | Anyone who may see the project | Registration, agreement, start, finish, inspections, reports, cancellation, in time order. |
| `POST /projects/{id}/assign-staff` | Head, Admin; staff for themselves | Who leads the project. Finished projects cannot change lead (409). |
| `GET /export/complaints.csv`, `GET /export/projects.csv` | Department/Admin (projects also Inspector) | CSV scoped to what the caller may see. Cells starting `= + - @` are stored as text. |

Complaints record `opened_on` and `resolved_on` (simulated calendar), so resolution times are measured in days on that calendar.

## 9. Resident accounts (e-mail + password), alongside Google and guests

| Method / path | Notes |
|---|---|
| `POST /auth/register` `{name, email, password}` | 201 with a session. Password: 8-128 characters, not a common password, not your e-mail name or name, mixing letters with numbers or symbols. One account per e-mail (409 `EMAIL_TAKEN`). Ten sign-ups per client per hour. |
| `POST /auth/resident/login` `{email, password}` | Same 401 for a wrong password and an unknown e-mail. Five failures for one e-mail from one client lock that pair for five minutes. |
| `POST /auth/resident/password` `{current_password, new_password}` | Signs out the other devices. Google accounts have no password (409). |
| `POST /me/complaints/claim` `{reference, code}` | Adds a report made as a guest to the account (needs the tracking code). Wrong guesses are throttled with the code-guessing limiter. |

Passwords are stored only as salted PBKDF2-SHA256 hashes; they cannot be read back by anyone. The e-mail is **not verified** (the app never sends e-mail), so there is no "forgot password" e-mail, and a local account is never merged with a Google account that has the same address. Google, local accounts and guests all work; none is required.
