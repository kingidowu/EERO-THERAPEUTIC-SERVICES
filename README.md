# Eero Therapeutic Services

Client intake and staff care-workspace prototype, with a separately testable backend foundation.

## Repository layout

- `dist/`: static website, simple client portal, intake and document capture, staff/admin workspace, company and clinician pages, official brand assets, and white paper.
- `backend/`: authenticated Flask staff-scheduling API, Python service layer, fictional-data AI adapters, SQLite development schema, PostgreSQL design, and backend tests.
- `tests/`: frontend flow tests.
- `brand-palette.json`: official-logo colors and website design tokens.

## Preview the website locally

From the repository root:

```bash
python -m http.server 8000 --directory dist
```

Open http://localhost:8000. The hosted preview is https://eero-care-workspace.oluwatimi007.chatgpt.site.

## Run the checks

```bash
node --test tests/*.test.cjs
python -m pip install -r backend/requirements.txt
cd backend
python -m unittest discover -s tests -v
```

## Browser flow checks

```bash
npm ci
npx playwright install chromium
npm run test:browser
```

The browser check starts and stops its own local preview server. It uses isolated fictional data and writes desktop/mobile screenshots to ignored `artifacts/`.

## Backend status

The care-workspace prototype uses browser-local storage and role previews. A separate shared staff scheduler (`dist/staff.html`) now connects to the authenticated Flask scheduling API when served by `backend/web.py`. Google OAuth credentials and staff identity mappings are still required; the public website has not been deployed with this backend. The AI adapter uses fictional data only and requires a separately provisioned API key. Do not commit keys, `.env` files, databases, or patient records.

Real-patient ingestion is disabled. This prototype has not been certified as HIPAA compliant. Production identity, hosted database/storage, BAAs, deployment security, backups, and independent review remain necessary. See `backend/README.md` for implemented capabilities and production requirements.

## Hosting

A static host can serve `dist/`. Hosting the source on GitHub does not run the backend. The source archive does not include the live hosting configuration. Confirm the existing hosting project and sharing settings before publishing.

## Scheduling and staff operations

Open `http://localhost:8000/?portal=admin`, then **Calendar** for the searchable agenda and month view. Sessions support therapist assignment, durations, overlap checks, attendance and cancellation history. Filters let staff find older sessions needing attendance updates. Counts summarize scheduled sessions today, upcoming unassigned sessions, missing attendance, and completed sessions.

The backend provides encrypted, authorized scheduling with UTC timestamps, case/clinician overlap checks, versioned edits and scoped agenda pagination. It now includes working hours, time off, finite recurring series, individual exceptions and future-occurrence editing. See [UPGRADE_ROADMAP.md](UPGRADE_ROADMAP.md) for the next frontend and backend upgrades.

Source files were restored from the original repository ZIP so changes and checks are directly reviewable. The ZIP is the original snapshot and does not include these upgrades.

## Shared staff scheduler: roadmap items 1, 2 and 3

The new [staff setup guide](backend/STAFF_SETUP.md) covers local configuration, Google Workspace OAuth client setup, membership mapping, and running the API-connected staff screen. Staff scheduling persists in the server database and is shared between authorized signed-in staff. Availability and series changes are enforced server-side. A real Google Workspace client has not yet been created or configured.

## Waitlist and staff follow-up board

The shared staff screen now includes **Staff tasks** and **Waitlist** tabs. Tasks support assigned staff, due dates, priority, overdue filters, editing, completion and reopening. Waitlist requests support priority, earliest date, recorded slot offers, decline/withdrawal, expiry and confirmed booking into the schedule. These workflows use the authenticated API and server persistence. No email or text message is sent.

Waitlist offers do not reserve time; acceptance rechecks availability and overlapping sessions. Only administrators, supervisors and assigned intake staff manage requests; clinicians can view requests for their assigned cases. Retried bookings return the original session without creating a duplicate. See [STAFF_SETUP.md](backend/STAFF_SETUP.md) for access, setup and deployment boundaries.

The [functional audit](FUNCTIONAL_AUDIT.md) records the control fixes, shared case/staff administration, verification commands, comparison with existing practice systems and remaining release dependencies.
