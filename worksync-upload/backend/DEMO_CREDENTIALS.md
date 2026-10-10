# Demo sign-in credentials (fictional, local demo only)

These dummy accounts exist only in the seeded demo database. Passwords are stored hashed (PBKDF2-SHA256); the
values below are the plaintext used by `seed.py`. **Never reuse them anywhere real.** The public (residents) does
not sign in: it can browse nearby works and report/track complaints without an account.

**On a hosted site** (see `../DEPLOY.md`) these passwords do not work: every account uses the single password set in
`WORKSYNC_STAFF_PASSWORD`. The usernames are the same.

| Username | Password | Role | Organisation | Acts as |
|---|---|---|---|---|
| `water.dept` | `Water@Dept26` | Department | Water Department | owns `water-1` |
| `telecom.dept` | `Telecom@Dept26` | Department | Telecom Department | owns `telecom-1` |
| `power.dept` | `Power@Dept26` | Department | Power Department | declares Power's planned work |
| `roads.dept` | `Roads@Dept26` | Department | Roads Department | owns the resurfacing projects |
| `water.staff` | `WaterStaff@26` | Department | Water Department | second Water team member |
| `telecom.staff` | `TelecomStaff@26` | Department | Telecom Department | second Telecom team member |
| `power.staff` | `PowerStaff@26` | Department | Power Department | second Power team member |
| `roads.staff` | `RoadsStaff@26` | Department | Roads Department | second Roads team member |
| `water.head` | `WaterHead@26` | Department head | Water Department | gets Water complaints that missed their promised date |
| `telecom.head` | `TelecomHead@26` | Department head | Telecom Department | same, for Telecom |
| `power.head` | `PowerHead@26` | Department head | Power Department | same, for Power (electrical complaints) |
| `roads.head` | `RoadsHead@26` | Department head | Roads Department | same, for road-surface complaints |
| `aqua.contractor` | `Aqua@Contr26` | Contractor | Aqua Pipeworks Ltd | Water main repair |
| `link.contractor` | `Link@Contr26` | Contractor | LinkDuct Infrastructure | Telecom duct work |
| `grid.contractor` | `Grid@Contr26` | Contractor | GridLine Electrical | Temple Street power work |
| `pave.contractor` | `Pave@Contr26` | Contractor | PaveWell Surfacing | final surfacing |
| `inspector.nisha` | `Inspect@Nisha26` | Inspector | Independent Inspectorate | inspections |
| `inspector.arun` | `Inspect@Arun26` | Inspector | Independent Inspectorate | second inspector |
| `admin` | `Admin@Work26` | Coordinator (administrator) | WorkSync Administration | sees every complaint, assigns unrouted ones, demo clock, sample scenario |

Complaints are routed by category: electrical goes only to Power, water only to Water, telecom only to Telecom and
road-surface damage only to Roads. Other categories go to the coordinator (`admin`), who assigns them. Inspectors and
contractors cannot see complaints. A department head can act on complaints that were escalated; ordinary department
staff cannot once a complaint is escalated.

Residents do not use these accounts. They are guests (no account), or optionally create their own account (e-mail + password, stored only as a salted hash)
or sign in with Google.

A **head of department** (`*.head`) can see every colleague in their department, what each is working on, their activity trail, and the department's
history; ordinary staff (`*.dept`, `*.staff`) see the department's numbers but only their own work and actions. The coordinator (`admin`) sees all departments.

Sign-in is checked on the server. Five wrong attempts for the same username from the same client lock that
combination for five minutes. Sessions last 8 hours and end on sign-out.
