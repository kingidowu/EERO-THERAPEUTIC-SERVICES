# Eero upgrade roadmap

## Implemented: scheduling and staff operations

- Agenda and month views; search by session, case or location.
- Date, therapist and attendance filters; responsive layouts and empty states.
- Therapist assignment, 15–240 minute durations, and attendance states.
- Overlap prevention for the same case or therapist; back-to-back appointments remain valid.
- Cancellation preserves session activity. Upcoming unassigned appointments and missing attendance updates are counted.
- Legacy browser records load as Scheduled, 60 minutes, and Unassigned.
- Local save failures roll back appointment edits and show a retryable error.
- Backend scheduling validates active assigned clinicians and case permissions, encrypts titles, normalizes timestamps to UTC, records audit events, and rejects stale updates using a version number.
- Backend agenda queries enforce tenant and assignment scope, timezone-aware ranges, and bounded pagination.
- SQLite serializes conflict checking and writes; the PostgreSQL scheduling migration is still pending.

The frontend remains a browser-local fictional-data preview. The Python service is separately tested and is not connected to the public website. Browser role previews are not authentication. This change does not send invitations or reminders, enable real-patient ingestion, or alter the live deployment.

## Suggested next upgrades, in priority order

| Priority | Frontend improvement | Backend work | Acceptance criteria |
| --- | --- | --- | --- |
| 1 | Real staff sign-in and shared schedule | Identity-provider validation, authenticated API adapter, server-derived principals, hosted database migration | Two signed-in staff see the same schedule; unauthorized users cannot access cases; concurrent scheduling cannot double-book |
| 2 | Therapist availability, working hours and time off | Availability rules, explicit organization timezone, daylight-saving validation; PostgreSQL exclusion constraints for clinician and case time ranges | Slots respect time off; conflicting writes from separate API workers fail atomically |
| 3 | Recurring appointments with “this session / future sessions” editing | Recurrence expansion, series identifiers, exceptions, bounded horizon and idempotency keys | Editing one occurrence preserves others; cancelling a series cannot recreate cancelled sessions |
| 4 | Waitlist and staff assignment board | Referral queue, service and availability matching, supervisor overrides, audit trail | Staff can offer a freed slot and track accepted/declined offers; no automatic clinical assignment |
| 5 | Reminder preferences and delivery status | Consent/preferences, background delivery queue, retry policy, deduplication and approved messaging provider | Cancellation suppresses reminders; retries do not duplicate messages; content excludes clinical details |
| 6 | Daily staff task board and caseload view | Assigned-task queries, due-date priorities, supervisor workload summaries and pagination | Staff see tasks for accessible cases; counts match the filtered underlying records |
| 7 | Session-to-note handoff and unsigned-note inbox | Appointment/encounter linkage, review workflow, versioned drafts and signature controls | Completed sessions link to drafts without implying clinical sign-off; reviewers can see outstanding notes |
| 8 | Accessible calendar and mobile polish | Server pagination and stable filtered APIs | Keyboard-only flows work; focus returns after dialogs; screen readers announce validation; long schedules remain usable |
| 9 | Operational reporting and billing preparation | Attendance aggregates, authorization/units tracking and explicit billing review | Reports reconcile to source sessions; no-show/cancelled records stay separate from delivered services |

## Implementation decisions still needed

- Choose the organization timezone and policy for viewing schedules while travelling.
- Define who can schedule, move and cancel sessions, and how late attendance can be corrected.
- Decide which location types require room/resource conflict checks (currently only case and therapist conflicts are enforced).
- Select identity, hosted storage and messaging integrations before connecting the existing patient-data workflows.
- Migrate existing preview sessions intentionally; Unassigned sessions must acquire an assigned active clinician before being saved to the backend.

## Validation

Run `node --test tests/*.test.cjs` and, from `backend/`, `../.venv/bin/python -m unittest discover -s tests -v` after creating the virtual environment and installing `backend/requirements.txt`.

Run `npm ci`, `npx playwright install chromium`, and `npm run test:browser` for the reusable end-to-end check. It starts and stops a local preview server and writes screenshots to `artifacts/`.

Browser validation covers scheduling, overlap rejection, attendance, cancellation, filtering, reload persistence and narrow-screen layout. The current public site is not changed by these local checks.
