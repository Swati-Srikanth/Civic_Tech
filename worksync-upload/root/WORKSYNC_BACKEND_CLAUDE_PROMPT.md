# Prompt for Claude — build the WorkSync backend

You are building the **backend only** for a new local demo app called WorkSync. Read the attached `WORKSYNC_API_CONTRACT.md` and follow its exact API paths, fields and statuses. The frontend will be designed separately in Stitch/Figma. Do not build React screens, redesign the UI, or write another long planning document. Implement runnable backend code, database, demo seed data and essential tests.

Target roughly four hours for backend implementation within a six-hour overall demo budget. Make routine coding decisions yourself. This is a local demonstrator, not a production municipal deployment.

## 1. Purpose

Departments register planned road work. Contractors confirm whether the proposed dates work. Departments approve one exact plan. Utilities finish and pass inspection before final resurfacing is authorised. Residents can see what is happening and why a project is blocked.

No maps, GPS, external APIs, LLM calls, SMS/email, uploads, payments, PDF, Docker or cloud deployment. Local HTTP APIs are necessary. Sequential work only; no parallel-work solver, emergency waivers or approval overrides.

## 2. Simple implementation

Use Python, FastAPI, Pydantic and SQLite through `sqlite3`. Keep the structure small:

```text
backend/
  main.py         # routes, CORS and startup/periodic review checks
  schemas.py      # request and response models
  db.py           # schema, connections and transactions
  auth.py         # demo user lookup and permissions
  scheduler.py    # pure date calculation
  service.py      # workflow, gate, mutations and audit
  seed.py         # fictional demo data
  tests/
  requirements.txt
  README.md
```

Expose FastAPI `/docs` for testing without the frontend. Bind locally. Seed a server-side user allowlist; `X-Demo-User` chooses a demo identity, not an arbitrary role. Four roles: DEPARTMENT, CONTRACTOR, INSPECTOR, ADMIN. Public road reads require no identity. There is no production-login claim.

Persist users, roads/expected utility departments, projects, cases, immutable plans, contractor responses, department approvals, inspections, declarations, incidents, audit and idempotency records. Use a SQLite file, not memory-only or browser storage.

## 3. Registration and schedule

Each project has one road, one owner department, one contractor, type UTILITY/RESURFACING, earliest start, hard finish deadline and positive duration. Utility duration includes excavation, testing and reinstatement. Keep execution status separate from planning status. One active coordination case per road, including standalone work; repeated detection must not create duplicates.

Support at most three utility projects and one resurfacing project in an active case. Larger/unsupported inputs stay BLOCKED with an explanation. All relevant known work must be considered; never silently omit projects to meet this limit.

For final surfacing review work due within 180 days after expected surface completion, plus any outstanding started work regardless of age. Unknown relevant dates block assessment. Work wholly outside that period stays visible with its exclusion reason. Recheck relevance after date changes; newly included scope needs a new plan. Previous actual surfacing creates a 180-day no-cut restriction; unresolved protected work stays blocked because waivers are not implemented.

Try all orderings of supported utility jobs, maximum six. For each:

- Inclusive dates: `end = start + duration - 1`.
- Utility start: maximum of its earliest start and prior utility finish + 2 days.
- Surface start: maximum of its earliest start and last utility finish + 4 days. With no utilities, use its earliest start; coverage and other gates still apply.
- Check every project's hard finish deadline, including contractor-updated earliest starts and resurfacing availability.
- Choose the valid plan with earliest final completion, using stable IDs to break ties. For a utilities-only case, minimise the last utility finish.

These buffers and the 180-day rule are explicitly **demo policy**. Return PLAN_FOUND, NO_SEQUENTIAL_PLAN with violated constraints, or UNASSESSABLE with missing fields. Never claim global impossibility.

## 4. Workflow and versions

`DRAFT → CONTRACTOR_REVIEW → DEPARTMENT_REVIEW → APPROVED → COMPLETED`; unresolved cases become BLOCKED.

- Each contractor responds for every assigned project in the exact plan version: ACCEPT, COUNTERPROPOSE a later earliest start, or REJECT with reason.
- A changed constraint creates a new immutable plan version and requires fresh responses. Do not carry consent forward automatically.
- After every contractor accepts, each owning department approves that exact plan. All owners are required; no majority vote. Contractor acceptance plus all owner approvals confirms the displayed dates; no extra acknowledgement stage.
- Admin can request revision before execution or keep a case blocked with a reason. Admin cannot impersonate contractors, override rejection or force clearance.
- Scope/date/duration/assignment edits and newly relevant work invalidate earlier responses/approvals before execution. Preserve history; stale submissions return 409.
- Normal on-time starts/finishes do not invalidate the plan. Material changes or delays after execution starts create a review hold; in-progress replanning is explicitly unsupported. Preserve actuals and block new starts.
- Cancellation is allowed only before physical work; never delete an existing trench/restoration obligation.
- Persist review deadlines of 48 hours. A small periodic task and command-time deadline checks block overdue reviews. Clock advance can demonstrate timeouts. Silence never means approval.

Use row `version` for concurrent changes, `material_version` for planning edits, immutable `plan_version` for consent, and road `registry_version` for declarations. Do not invalidate a declaration merely because a contractor reports normal completion.

## 5. Execution and final resurfacing gate

Implement all gate rules in backend functions. GET gate is read-only.

Authorise a start only when the current case/plan is approved, all consent is current, the user is the assigned contractor, the date matches the approved start and no hold/protected-surface blocker exists. Earlier utility jobs must be completed with the planned separation.

Before resurfacing additionally require:

1. Every relevant known utility job is DONE with explicit testing/reinstatement completion declarations.
2. Independent inspector UTILITY_RELEASE=PASS; inspection date at least three days after utility finish; surface starts at least the day after inspection.
3. Every seeded expected utility department has a current, registry-bound declaration covering all work through the 180-day review horizon. “A project is registered” alone is not adequate coverage. NO_PLANNED_WORK cannot contradict known work.
4. No new relevant project, missing/failed inspection, expired declaration, changed version or incident hold.

POST start atomically re-reads current inventory, checks all rules, issues a numbered PCC for resurfacing and records the contractor's reported start at the current demo time. This deliberately combines certificate issuance and immediate use. No backdated authorisation and no client-supplied status. A denied request creates no actual-start fact or invented violation.

Finish records current actual date; utility testing/reinstatement declarations are mandatory. Inspector cannot verify their own submitted evidence. Failed inspections hold the case. Resurfacing requires FINAL_SURFACE=PASS before completion; utilities-only cases require release inspection for every included utility. Preserve physical completion separately from verification.

Incident reporting records a claim that work happened without clearance or a site problem, adds a hold and appears in Admin review. It never retrospectively grants permission.

## 6. Integrity and frontend handoff

Use foreign keys and `BEGIN IMMEDIATE` transactions. Recheck permissions/current versions before changes. Persist business changes, audit and idempotency result together. Require keys scoped by user/action/payload; identical retries do not duplicate events, while changed payload with reused key returns 409. Check access before replay. Audit rows are append-only through triggers.

Implement `WORKSYNC_API_CONTRACT.md`, configurable localhost CORS, structured errors, filtered public output, and server-computed `allowed_actions`. Do not rely on disabled frontend buttons for security. OpenAPI must document exact schemas with examples so the frontend developer can wire forms directly.

## 7. Seed, tests and delivery

Demo clock starts 8 Nov 2026. Seed dedicated fictional contractors and separate department/inspector users:

- Market Road: Water earliest 8 Nov, duration 5, deadline 20 Nov; Telecom earliest 13 Nov, duration 4, deadline 22 Nov; surface earliest 10 Nov, duration 4, deadline 24 Nov.
- Expected sequential plan: Water 8–12, Telecom 14–17, surface 21–24 Nov.
- Expected utility departments: Water, Telecom, Power. Initially omit Power's declaration to demonstrate a gate blocker. Required approval owners are only Water, Telecom, Roads.
- Temple Street: Power earliest 30 Nov, duration 5, deadline 31 Dec; surface earliest 12 Nov, duration 3, deadline 20 Nov: no valid sequential plan.
- Station Road can remain empty to demonstrate the empty state.

Test the schedule, blocked/unknown inputs, wrong-role direct calls, stale approvals, declaration/inspection gate failures, read-only GET, idempotent retries, registration/start race, timeout, normal completion and restart persistence. Report actual test results, not assumed passes.

Deliver runnable backend, requirements, seed command, tests, `/docs`, `/openapi.json`, and a concise README with Windows-friendly startup commands. Include exact fixture examples and a short endpoint walkthrough for the frontend builder. If constrained, simplify code organisation or documentation; keep permissions, stale checks, gate, audit and persistence. Start coding now.
