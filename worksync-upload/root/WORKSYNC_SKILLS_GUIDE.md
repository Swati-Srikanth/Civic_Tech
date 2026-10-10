# WorkSync — skills and tools explained separately

Here “skills” means the development concepts you should understand, not extra plugins or installed Claude skill packages. You can build with AI assistance while learning these basics; a separate long course is not part of the six-hour build.

## 1. Skills you need

| Skill | Plain meaning | Enough for this project |
|---|---|---|
| Python functions and conditions | Turn rules into repeatable decisions | Read “if inspection missing, refuse start”; understand function inputs/outputs |
| FastAPI basics | Give the frontend URLs that run backend functions | Recognise GET reads, POST actions, PATCH edits, request validation and `/docs` |
| JSON | Structured messages shared by both sides | Read objects, arrays, booleans, IDs and date strings without renaming fields |
| SQLite and SQL | Store information after the program stops | Understand tables, IDs, relationships, SELECT/INSERT and why browser state is insufficient |
| Transactions | Several changes succeed together or none do | Start, certificate and audit must commit together; no half-completed approval |
| Roles and ownership | Decide who can act on which records | A contractor cannot approve for a department or edit another contractor's project |
| State machines | Define which step is allowed next | Follow draft → contractors → departments → approved; understand blocked paths |
| Versions | Identify which exact plan someone accepted | Old approval cannot automatically approve changed dates |
| Idempotency | Prevent a retry/double click from acting twice | Same action key and payload returns the original result |
| React components and forms | Reusable visible parts with user input | ProjectCard, form values, loading/error state and refreshing after a save |
| API integration and CORS | Let the frontend call the separate backend | Set the base URL, allow localhost frontend origin, send expected headers, read errors |
| Tests and debugging | Check behaviour, including refusal paths | Read terminal errors and test both valid actions and actions that must fail |

## 2. Tools are different from skills

| Tool | Job in this workflow |
|---|---|
| Claude in a coding environment | Writes/runs backend code and can handle final frontend wiring |
| Stitch/Figma | Produces the design handoff you choose; runnable source, if available, can be reused |
| Python + FastAPI | Runs the backend |
| SQLite | Stores the local database |
| React + Vite | Runs the frontend implementation |
| Browser and FastAPI `/docs` | Lets you see screens and test endpoints |
| Editor and terminal | Start the two processes and inspect errors |

No map service account, API key, paid database or AI API is required by this architecture. The model tools you choose are separate from the app's runtime dependencies.

## 3. What you should check personally

1. Register the sample projects and read the proposed dates. Ask why the surface starts after utility completion and inspection.
2. Accept as each contractor, then approve as each department. Watch the plan move through its states.
3. Edit a duration before execution. Confirm that the old approvals stop counting.
4. Try paving before the required inspection or Power declaration. It must fail with a useful explanation.
5. Complete the missing requirement and try on the approved date. Confirm that the start and PCC are saved.
6. Refresh the browser and restart the backend. The project and audit history must remain.

If those checks pass through real endpoints, you have evidence that the core flow works. An attractive screen with hardcoded “Approved” labels does not establish this.

## 4. Learning order for understanding your demo

Start with **API/JSON → SQLite → workflow states → versions and permissions → clearance gate → React integration**. This order follows the actual movement of data through the app. Leave GIS, distributed systems, optimisation solvers, cloud hosting, advanced authentication and emergency legal workflows for later versions.

You should be able to explain: “The interface collects requests. The backend applies deterministic rules. SQLite records the decisions. Changed plans need fresh consent, and resurfacing starts only after current checks pass.”
