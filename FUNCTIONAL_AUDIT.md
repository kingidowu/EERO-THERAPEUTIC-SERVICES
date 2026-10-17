# Functional audit — October 17, 2026

This pass fixes controls and fills workflow gaps in the editable app. It is a tested development preview, with a separate authenticated shared staff workspace. It is not a production certification or a claim that every possible input, browser, or external service is verified.

## Changes

- Made the desktop sidebar scroll above its footer so Chart Navigator and Care Plans can be clicked at common laptop heights.
- Connected the header avatar to workspace help and links; repaired public-page links back to client intake.
- Added case-profile actions for editing, chart navigation, session planning, and follow-up planning. Added local task editing and deletion.
- Made failed browser-storage saves restore the last committed workspace; blocked overlapping edits while saving. Restricted capture uploads to nonempty PNG, JPEG, or PDF files of at most 15 MB.
- Recovered chart navigation when a selected case disappears after reset. Encounter rows now distinguish missing notes from saved drafts.
- Added authenticated case creation, rename, close/reopen, team assignment and access removal. Changes enforce role/case scope, expected versions, encrypted labels and audit events. Closure requires resolving future sessions, active waitlist requests and open tasks. Staff removal requires reassigning or resolving their future sessions/open tasks.
- Added shared schedule filter reset, print and RFC 5545 calendar download, plus task-filter reset. Exports explicitly contain loaded sessions only. Calendar files use stable identifiers, escaped text, UTC times and UTF-8 line folding.
- Preserved task-assignee filters after workspace refresh. Existing sessions can be cancelled after their clinician becomes inactive; this exception cannot create a new session for inactive staff.

## Verification

Run from the repository root:

```sh
PYTHONPATH=backend .venv312/bin/python -m unittest discover -s backend/tests
npm test
PYTHON_BIN=.venv312/bin/python npm run test:browser
```

The backend suite contains 79 tests; the JavaScript suite contains 12 tests. Four browser flows exercise local scheduling, authenticated shared scheduling, staff tasks/waitlist, and the broader workspace audit. The isolated shared fixture uses synthetic Google provider responses, while separate tests verify signed OIDC token validation. It does not prove live Google OAuth connectivity.

The workspace audit follows browser controls through API writes, database persistence, bootstrap reads and a second staff identity. It checks case creation/assignment/rename/closure/reopening, role visibility, session handoff, help, clear filters, print invocation, mobile width, every local sidebar target, case reload persistence, failed-save rollback/retry, task edit/delete, reported medication/allergy entries, history, encounters, SOAP drafts, care-plan progress and client intake routing. Existing flows check conflict rejection, recurrence, time off, stale updates, task completion/reopening, confirmed waitlist booking, logout and data clearing on denied access. Screenshots are generated under ignored `artifacts/`.

Calendar serialization tests cover UTC conversion, escaped delimiter/newline text, stable identifiers, invalid dates/IDs and 75-octet line folding. Printing is checked by intercepting `window.print`; physical printers and external calendar importers are not tested.

## Comparison with existing systems

Primary product documentation reviewed for workflow comparisons:

| Reference | Relevant behavior | Eero status / next work |
| --- | --- | --- |
| [SimplePractice waitlist](https://support.simplepractice.com/hc/en-us/articles/19385683508237-Managing-the-client-waitlist) | Track demand and turn openings into appointments | Staff waitlist, offers and confirmed booking implemented; automatic outreach remains unconnected. |
| [SimplePractice appointment requests](https://support.simplepractice.com/hc/en-us/articles/207624876-Enabling-online-appointment-requests) | Client requests linked to clinician availability | Staff-side availability and conflict checks implemented; authenticated client appointment requests remain future work. |
| [TherapyNotes scheduling](https://support.therapynotes.com/hc/en-us/articles/30661279632539-Quick-Start-Scheduling) | Schedule-centered staff workflow | Shared sessions, recurrence, attendance and case handoffs implemented in the development adapter. |
| [TherapyNotes notes](https://support.therapynotes.com/hc/en-us/articles/30661345691419-Quick-Start-Notes) | Documentation tied to clinical work | Local encounters, note drafts and follow-up controls exist; shared clinical records, signatures and amendment workflow remain future work. |
| [RFC 5545](https://www.rfc-editor.org/rfc/rfc5545) | Calendar interchange format | Added `.ics` downloads; no external calendar synchronization. |

These are workflow references, not claims of feature parity or copied implementations.

## Remaining release work

1. Create/configure the requested Google Workspace OAuth client, register the deployed callback URL and map authorized staff identities. This requires the organization's Google Cloud account.
2. Implement and integration-test the hosted PostgreSQL runtime, private document storage, recovery and deployment configuration. Current shared persistence uses the SQLite development adapter; SQL blueprints are unapplied.
3. Connect client identity/intake and clinical records to reviewed server APIs. The browser-local preview and shared staff records are separate; local role buttons are previews, not authentication.
4. Add messaging delivery and consent/preferences before advertising appointment reminders or automatically contacting waitlisted clients. Current offers send no messages.
5. Finish the production review and real-user acceptance pass before real patient records are enabled. Existing backend documentation describes these boundaries.
6. Resolve the GitHub account billing lock so hosted Actions can run. Local results remain available; no production website deployment was performed by this pass.
