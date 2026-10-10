# WorkSync — shared API contract

Give this file to the backend builder and the frontend builder. These are proposed interfaces to implement, not existing endpoints. Use this contract with the backend and frontend briefs supplied alongside it; it replaces the earlier combined prompt's interface choices for this build.

## 1. Connection rules

- Backend: `http://localhost:8000`; prefix: `/api/v1`.
- Frontend: `http://localhost:5173`; configure its backend base URL with `VITE_API_BASE_URL`.
- FastAPI must allow this exact frontend origin through CORS, including `Content-Type`, `X-Demo-User` and `Idempotency-Key` headers. Do not use wildcard origins as a substitute for configuration.
- Internal calls send `X-Demo-User: <seeded-user-id>`. The server resolves role/org/assignment. Public reads do not require that header.
- POST/PATCH requests send `Idempotency-Key`. Keep the same key when retrying the same action after a network failure; create a new key for a new or changed action.
- Mutations of existing subjects send `expected_version` from the latest server response. Contractor responses and department approvals additionally send `plan_version`.
- Dates: `YYYY-MM-DD`, inclusive endpoints. Recorded timestamps: UTC ISO 8601. Work dates and the demo clock use Asia/Kolkata.
- No maps or third-party APIs. This HTTP contract connects the app's own frontend and backend.

## 2. Shared vocabulary

| Field | Allowed values |
|---|---|
| role | `DEPARTMENT`, `CONTRACTOR`, `INSPECTOR`, `ADMIN` |
| project.kind | `UTILITY`, `RESURFACING` |
| project.execution_status | `PLANNED`, `IN_PROGRESS`, `DONE`, `CANCELLED` |
| case.status | `DRAFT`, `CONTRACTOR_REVIEW`, `DEPARTMENT_REVIEW`, `APPROVED`, `BLOCKED`, `COMPLETED` |
| contractor decision | `ACCEPT`, `COUNTERPROPOSE`, `REJECT` |
| department decision | `APPROVE`, `REJECT` |
| inspection.kind | `UTILITY_RELEASE`, `FINAL_SURFACE` |
| inspection.result | `PASS`, `FAIL` |
| declaration.mode | `ALL_WORK_REGISTERED`, `NO_PLANNED_WORK` |
| assessment.outcome | `PLAN_FOUND`, `NO_SEQUENTIAL_PLAN`, `UNASSESSABLE` |

`version` is a row concurrency counter. `material_version` identifies changed project planning inputs. `plan_version` identifies immutable proposed dates and scope. Routine execution changes increment row versions, not material versions. A road's `registry_version` changes only when relevant registered planning scope changes; declarations bind to that registry revision. UI treats all versions as opaque server values.

`allowed_actions` uses these fixed identifiers as applicable to the resource: `CREATE_PROJECT`, `EDIT_PROJECT`, `CANCEL_PROJECT`, `GENERATE_PLAN`, `RESPOND`, `APPROVE_PLAN`, `REVIEW_CASE`, `START_PROJECT`, `FINISH_PROJECT`, `INSPECT_PROJECT`, `DECLARE_WORKS`, `REPORT_INCIDENT`. Bootstrap may expose global actions for the selected authenticated demo user; public bootstrap never grants staff permission. Changing the user requires refetching internal views and actions.

`assigned_contractor_id` is the contractor organisation ID, not an arbitrary user ID; assignment permission compares it with the authenticated demo user's `org_id`. Project responses expose the same input fields plus `id,version,material_version,owner_org_id,case_id,execution_status,actual_start,actual_end,inspection_status,allowed_actions`. `inspection_status` is PENDING/PASS/FAIL; `actual_*` and `case_id` may be null. Display names are separate fields, not substitutes for IDs. Public cards expose `proposed_start,proposed_end,confirmed_start,confirmed_end,actual_start,actual_end,verified_on` with null for unavailable dates, plus the whitelisted title/purpose/organisation names, execution status and public reason.

## 3. Endpoint contract

All paths below are relative to `/api/v1`. Successful reads return 200, creates return 201, and actions return 200. Lists return `{ "items": [...] }`. Detail responses return the resource object. Mutation results include the updated subject `id`, `version`, any changed `case_id`, and `message`; the UI then refreshes relevant details.

| Method/path | Access | Request / response |
|---|---|---|
| GET `/bootstrap` | Public demo metadata | Demo users `{id,name,role,org_id}`, contractor organisations `{id,name}`, roads `{id,name,version}`, current `{date,version}` demo clock, and labelled demo policy |
| GET `/roads/{road_id}/public` | Public | Road, project cards, public case status, labelled dates, public block/delay reasons; no internal audit/notes |
| GET `/projects?road_id=...` | Internal | Visible projects; each includes `version`, `material_version`, current case, execution/inspection status and `allowed_actions` |
| POST `/projects` | Owning department | `title,purpose,road_id,kind,assigned_contractor_id,earliest_start,deadline,duration_days`; owner derived from user; returns created project/case IDs |
| PATCH `/projects/{id}` | Owning department | `expected_version` plus changed planning fields; returns project and any invalidated case |
| POST `/projects/{id}/cancel` | Owning department | `expected_version,reason`; rejects cancellation after physical work starts |
| GET `/cases?road_id=...` | Internal | Cases with current status, version, plan version and actions |
| GET `/cases/{id}` | Internal | Case detail as below, with schedule, responses, approvals, project versions, declarations required and audit link |
| POST `/cases/{id}/plans` | Owning department/Admin | `expected_version`; generate a supported sequential plan or persist a blocked assessment |
| POST `/cases/{id}/responses` | Assigned contractor | `expected_version,plan_version,project_id,decision,reason?`; COUNTERPROPOSE also needs `earliest_start` |
| POST `/cases/{id}/approvals` | Required department | `expected_version,plan_version,decision,reason?`; approval covers all that owner's displayed projects in this plan |
| POST `/cases/{id}/review` | Admin | `expected_version,action,reason`; action `REQUEST_REVISION` or `KEEP_BLOCKED`; never force approval. REQUEST_REVISION returns an unstarted case to DRAFT, preserving history |
| GET `/projects/{id}/gate` | Internal | Pure read: eligibility, current blockers and versions; example below |
| POST `/projects/{id}/start` | Assigned contractor | `expected_version,plan_version`; rechecks current inventory/gate, records reported start now, issues PCC if resurfacing; returns `pcc_number` or null |
| POST `/projects/{id}/finish` | Assigned contractor | `expected_version,delay_reason?`; utilities additionally require `testing_complete:true,reinstatement_complete:true` |
| POST `/projects/{id}/inspections` | Inspector | `expected_version,kind,result,notes`; inspected date is current demo date; returns inspection ID and updated project version |
| POST `/roads/{id}/declarations` | Utility department | `expected_version,mode,covers_from,covers_through,valid_until`; server captures registry revision and known project set |
| POST `/projects/{id}/incidents` | Responsible department/contractor, Inspector/Admin | `expected_version,kind,description,occurred_date?`; kind `WORK_WITHOUT_CLEARANCE` or `SITE_ISSUE`; record claim and review hold, no retrospective authorisation |
| GET `/cases/{id}/audit` | Authorised internal | Read-only events `{id,recorded_at,actor_name,action,reason}` |
| POST `/demo/clock/advance` | Admin, local demo only | `expected_version,days`; positive integer, forward-only; persist clock and process due reviews |

For `expected_version`, the subject is the project, case, road or demo clock named in the route. Case detail exposes each project version separately. The backend maintains all affected case/road versions atomically. Staff action visibility uses `allowed_actions`, but the backend still rechecks permission.

## 4. Case detail shape

This is a **mock fixture** for UI development. Names, IDs and dates are fictional. A generated interface must fetch real data when integrated.

```json
{
  "id": "case-market",
  "road_id": "road-market",
  "road_name": "Market Road",
  "version": 4,
  "status": "CONTRACTOR_REVIEW",
  "plan_version": 1,
  "deadline_at": "2026-11-10T02:30:00Z",
  "assessment": {"outcome": "PLAN_FOUND", "messages": []},
  "schedule": [
    {"project_id": "water-1", "project_version": 1, "title": "Water main repair", "kind": "UTILITY", "start": "2026-11-08", "end": "2026-11-12", "date_label": "PROPOSED"},
    {"project_id": "telecom-1", "project_version": 1, "title": "Telecom duct work", "kind": "UTILITY", "start": "2026-11-14", "end": "2026-11-17", "date_label": "PROPOSED"},
    {"project_id": "surface-1", "project_version": 1, "title": "Final road surface", "kind": "RESURFACING", "start": "2026-11-21", "end": "2026-11-24", "date_label": "PROPOSED"}
  ],
  "responses": [],
  "approvals": [],
  "required_departments": ["water", "telecom", "roads"],
  "coverage_required": ["water", "telecom", "power"],
  "hold": false,
  "public_reason": null,
  "allowed_actions": ["RESPOND"]
}
```

Responses include `{project_id,plan_version,decision,reason}`; approvals include `{org_id,plan_version,decision,reason}`. Detail serializers may add display fields while preserving these names. Generate a complete validated schema and fixture examples in FastAPI's OpenAPI document; do not introduce conflicting aliases in frontend code.

## 5. Gate and error shapes

```json
{
  "project_id": "surface-1",
  "version": 7,
  "plan_version": 1,
  "eligible": false,
  "not_an_authorisation": true,
  "blockers": [
    {"code": "COVERAGE_MISSING", "message": "Power department has not confirmed its planned work.", "responsible_org_id": "power", "next_action": "Request its declaration."}
  ]
}
```

```json
{
  "error": {
    "code": "STALE_PLAN",
    "message": "This plan changed. Refresh it before responding.",
    "failures": []
  }
}
```

Use 401 missing demo identity, 403 wrong authority, 409 stale version/state/idempotency mismatch, 422 invalid data/gate failure, and 503 retryable database contention. A persisted `NO_SEQUENTIAL_PLAN` is a normal assessment result, not an HTTP server failure. UI must retain form input, show the server message and refresh on stale errors; it must not silently replay consent against a newer plan.

Normalise FastAPI validation errors to this same error envelope. Within a mutation transaction, check current access first, then matching idempotency replay, then expected versions for a new action. A valid replay returns its original result and timestamp; it does not repeat the action or imply an old permission is still current.

## 6. Integration acceptance

Both builders use these enums, fields and paths. Frontend uses one `api.ts` client; backend exposes `/docs` and `/openapi.json`. Remove mock state as the source of truth before demonstration. Changing a project in the frontend must appear in SQLite and case history, survive reload, invalidate old consent when appropriate, and display the real backend gate result. Designs alone do not complete this wiring step.
