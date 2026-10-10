# Prompt for Stitch/Figma — simple WorkSync frontend

Design the frontend for **WorkSync — What's happening on my road**. Backend development is separate. Use my supplied template as the visual reference when available. Keep the app simple enough to implement and connect within a six-hour MVP build.

Use the accompanying `WORKSYNC_API_CONTRACT.md` for data names, states and available actions. This is a frontend brief, not a request to design backend logic. If this environment creates runnable frontend code, use React/Vite-compatible components. If it creates designs only, provide clearly named frames, reusable components, form fields and state variants for the implementation handoff.

## 1. Design direction

- Mobile first, 390 × 844; desktop 1280 × 800.
- Navy `#0F2A4A`, background `#F8FAFC`, white cards, light borders, radius 12px, 8px spacing grid. Use teal as an accent; dark teal `#087F73` for white-text buttons.
- Inter if locally available, with system sans-serif fallback. Body text about 16px; readable headings, visible keyboard focus, labelled forms and roughly 44px touch targets.
- Text and icons accompany every status colour. Check contrast; never use faint grey essential text or colour-only warnings.
- No maps, geolocation, illustrations, animation, external API integrations, complex charts or decorative dashboards. Use a road dropdown, cards, simple tables and a short progress stepper.
- One obvious primary action per task. Explain what is missing and who needs to act. Do not expose hashes, raw JSON or internal database terminology in ordinary screens.

## 2. Four screens only

### A. My road — public

Header: WorkSync, short description and road selector. Public access has no login. A separate **Demo workspace** entry opens the staff view.

Each project card answers: **What work? Why? Which department and contractor? When? Current status?** Show PROPOSED, CONFIRMED, ACTUAL and VERIFIED dates distinctly. Never label a proposed date as a promise.

Use plain-language notices such as “Waiting for Power department to confirm its planned work.” Show an informative empty state when a road has no projects. Footer: “Checks known registered work; cannot physically prevent unregistered excavation.”

### B. Projects — department staff

List own projects with road, dates and state. Primary action: **Add project**.

Simple form: title, purpose, road, utility/resurfacing type, assigned contractor, earliest start, finish deadline and duration. Owner is filled by the selected demo user. Labels stay visible; error messages appear beside fields. Date/duration helper text should be brief.

Editing approved planning details shows: “Changing this plan will require fresh responses and approvals.” After saving, show the real backend detection result and **Open coordination case**. Do not imply a successful save until the server confirms it.

### C. Coordinate work — contractor and department actions

Top: road, status, plan version and response due time. Show a three-step progress indicator: **Contractors → Departments → Ready for work**.

Schedule table on desktop; stacked project/date cards on mobile. Below it, show who has responded and who is still pending.

- Contractor: **Accept these dates**, **Suggest a later start**, **Cannot do these dates**. Later start gets one date field; rejection requires a reason.
- Department: **Approve plan** or **Reject with reason**.
- Admin: **Request revision** or **Keep blocked** with a reason. No “force approve” control.

Use role-specific action panels and server `allowed_actions`. A stale response must say “This plan changed. Refresh to review the latest dates.” Never silently submit consent for a newer version.

### D. Work and checks — contractor, inspector and Admin

Use project cards with a compact checklist: approved plan, utility work complete, release inspection, utility declarations and date readiness.

Contractor actions: **Authorise and start now**, **Report finished**, **Report a site issue**. Utility completion includes explicit testing/reinstatement checkboxes.

Inspector actions: **Record release inspection** or **Record final inspection**, result PASS/FAIL and short notes. Department users can submit their own utility-work declaration, with review dates prefilled from backend data.

Show blocked start reasons as clear sentences with responsible department and next action. Example: “Telecom's release inspection is missing. The inspector must record it before paving can start.” Successful resurfacing displays the PCC number returned by the backend.

Admin sees blocked cases and an expandable activity history. Put the demo clock advance control here, clearly labelled simulated time. It does not grant approval.

## 3. Status wording

| Backend value | User-facing text |
|---|---|
| DRAFT | Plan being prepared |
| CONTRACTOR_REVIEW | Waiting for contractors |
| DEPARTMENT_REVIEW | Waiting for departments |
| APPROVED | Plan agreed — start checks still required |
| BLOCKED | Needs review |
| COMPLETED | Finished and checked |

Plan approval does not mean resurfacing is cleared. Show start eligibility separately.

## 4. States and handoff

Design loading, empty, success, blocked, validation-error, permission-denied and stale-plan states. Keep entered form data after errors. Prevent duplicate clicks while an action is pending, but rely on backend idempotency for correctness.

Use contract fixtures for previews and label them demo data. Do not calculate approval, scheduling or start eligibility in the frontend. After integration, all displayed state comes from API responses and survives a page reload.

If producing code, place HTTP calls in one `src/api.ts` client using `VITE_API_BASE_URL`; carry the selected demo identity and idempotency key, and refetch after mutations. If producing design frames, include a component/action mapping to the contract so the implementer can connect them without guessing.

Deliver reusable ProjectCard, StatusBadge, DateLabel, ScheduleList, ActionPanel, GateChecklist and EmptyState components/frames. Keep names aligned with these four screens. No additional screen is necessary for the first demo.
