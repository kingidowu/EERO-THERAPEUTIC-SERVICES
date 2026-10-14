# Eero backend foundation

This is an implemented, locally testable service layer for the Eero workspace. It is **not a certified HIPAA system** and is **not connected to the hosted prototype**. Real patient ingestion is disabled in this adapter. Do not put real patient data into the frontend or this development database.

## Implemented

- Organization isolation, active staff membership, roles, and case assignments checked in the service layer.
- Cases, quarantined documents, separate note types, tasks, authorization evidence, and append-only development audit history.
- AES-256-GCM encryption of case labels, document titles/content, note bodies, and task titles. Authentication data binds ciphertext to its organization and record.
- Uploaded PDF/JPEG/PNG size and signature checks. All files start quarantined; reads and approvals fail until a trusted scanner result is recorded.
- Separate reviewer approval; psychotherapy note reads restricted to their author. Disclosure exceptions are deliberately not implemented.
- Deterministic operational summary for pending reviews, overdue tasks, and expired authorization records. No clinical recommendations, AI inference, or automatic disclosures.
- Test coverage for cross-organization and unassigned-case access, revoked staff, encryption tampering, quarantine, separation of duties, note isolation, audit immutability, and operational rules.

## Run with fictional information

Create a virtual environment and install `requirements.txt`, then run from this folder:

```bash
python -m unittest discover -s tests -v
```

The authenticated Flask HTTP API is in `web.py`; its `Principal` is constructed from a server session created only after verified OIDC identity and staff mapping. There is no public credential or production authentication bypass. Staff provisioning remains an offline administrator operation; tests use isolated fixtures. See `STAFF_SETUP.md` for local setup and Google client provisioning.

## Production database and storage design

Use a managed PostgreSQL database for relationships, transactions, indexed queries, and organization isolation. Store file bodies in a private object store rather than database rows. The SQLite adapter is only for development checks; it has not been load-tested and must not be described as a large production database.

The intended record model includes organizations, staff membership, clients, guardian relationships, cases, staff assignments, referrals, service authorizations, encounters, treatment plans, versioned progress notes, separately restricted psychotherapy notes, documents and file versions, consent/disclosure evidence, programs/enrollments, tasks, approved billing events, access/disclosure history, and a durable job queue.

The implemented subset is defined by `schema.sql`. `postgres_blueprint.sql` supplies a broader PostgreSQL schema for clients, guardian evidence, encounters, document versions, progress notes, psychotherapy notes, programs, enrollments, tasks, authorizations, and audit events. It has not been applied or integration-tested. Row-level security is enabled and forced without permissive policies, so a correctly configured non-owner application role is denied access until reviewed policies are supplied. The broader modules remain planned service functionality. Before production, require organization-specific and case-specific row-level policies and a least-privilege database role; use pooling; implement pagination and concurrent mutation checks; keep audit access separate from clinical records. A tenant parameter alone is insufficient protection without an authenticated membership boundary.

For a photographed form, the production sequence is authenticated upload → size/signature verification → encrypted quarantine object → malware scan → approved OCR service → extraction draft → staff review → versioned record. OCR must not automatically overwrite verified clinical records. File names, request bodies, signed URLs, and clinical text must never enter ordinary application logs. Object keys use opaque IDs. Use short-lived signed access links after server authorization, not publicly readable buckets. Camera capture should avoid storing documents in device photo galleries wherever the browser permits it.

## Required before any patient-data launch

1. Eero identifies its responsible privacy/security officials and confirms the data types, workflows, jurisdictions, client age groups, and applicable contracts. Review New Jersey confidentiality/minor and guardian access requirements and assess whether 42 CFR Part 2 applies. Do not treat ordinary consent as blanket authorization for restricted disclosures.
2. Execute applicable BAAs with every provider/subprocessor handling ePHI. Verify the specific services, plans, locations, support access, and contract coverage. No BAA has been verified for the current demo hosting.
3. Integrate a validated identity provider with MFA, revocation, timeout/lock controls, least-privilege roles, staff onboarding/offboarding, and verified per-case access. Implement and review exceptional access procedures; do not automatically give administrators psychotherapy note access.
4. Configure managed encryption keys, secret management and rotation; TLS-only database/API connections; private networking where appropriate; restrictive storage/IAM rules; and separation between development and production.
5. Integrate trusted malware scanning, OCR, queue workers, retry/idempotency handling, upload cleanup, and tested review/versioning workflows. No external AI processor receives PHI until approved agreements, purpose limitations, and data controls are verified.
6. Implement durable audit export with restricted append-only access and independently retained immutable copies. The SQLite hash chain is for development validation; a database administrator can defeat it, and it is not a production immutability guarantee. Audit failed access attempts at the authenticated gateway without logging PHI.
7. Implement and test encrypted backups, restore drills, recovery objectives, retention/legal holds, authorized deletion, incident response and breach handling, monitoring, rate limits, vulnerability management, and independent penetration testing.
8. Implement patient access/amendment/disclosure workflows, guardian authorization, restricted-record segmentation, electronic signature verification where applicable, and approved clinical forms. Authorization metadata does not establish legal validity by itself.
9. Complete a documented risk analysis and remediation review, organizational policies and staff training, and clinical/privacy/security review of the complete deployed system. Verify backup and logs providers as well as primary database vendors.
10. Enable real-patient ingestion only in a separately reviewed production adapter. The local adapter's safety lock is not a compliance attestation.

## Validation limits

Current checks cover the local Python service layer, not live identity, hosted PostgreSQL, backup recovery, storage security, clinical usability, regulatory certification, or capacity. Audit actions contain opaque IDs but those identifiers and metadata must still be treated as sensitive. Local SQLite stores some metadata unencrypted; production must encrypt its full storage and backups. Development keys come from test memory; production key provisioning is not implemented.

## Primary references

- HHS cloud computing guidance: https://www.hhs.gov/hipaa/for-professionals/special-topics/health-information-technology/cloud-computing/index.html
- HHS Security Rule summary: https://www.hhs.gov/hipaa/for-professionals/security/laws-regulations/index.html
- HHS mental health and psychotherapy note protections: https://www.hhs.gov/hipaa/for-professionals/faq/does-hipaa-provide-extra-protections-mental-health-information-compared-other-health.html

These references guide the design. They do not establish that this implementation is compliant or approved.

## AI adapter and role previews

`ai_adapter.py` provides local, sample-data-only OpenAI Responses adapters for PNG/JPEG extraction and structured clinician-review briefings. Every extracted field requires review; extraction never automatically changes a chart. The briefing excludes contact fields and does not establish diagnoses. It requires an explicit fictional-data flag and an API key in an ignored `.env.local` or environment variable. The hosted static preview does not call this adapter and presents its extraction example as a sample. The 24 development tests and a live fictional briefing smoke check passed.

The frontend contains client intake, intake routing and assignment, clinical chart tabs, reported medication/allergy lists, draft SOAP/DAP notes, encounters, and care goals. These are browser-local prototype features. Role buttons are previews, not identity or authorization controls. No frontend intake syncs to the development database.

## Client experience preview

The default entry page now introduces the client preview with a separate staff-workspace link. The client home has four sections: Home, Intake form, Documents, and My request. Client request lists show only submissions tracked as created through this browser's client preview. Later attachments are placed with the existing intake; for assigned requests they also enter the case's document-review queue. No account authentication or per-user server-side data isolation is implied. Four frontend flow tests cover request filtering, upload rejection, assigned-case routing, and storage-failure rollback.

## Scheduling service additions

`Backend.save_appointment(principal, case_id, clinician_id, title, starts_at, duration=60, location='Office', status='Scheduled')` creates a fictional session. `starts_at` must carry a timezone offset; timestamps are stored in UTC. Clinicians must be active and assigned to the case. Overlapping case or clinician sessions are rejected, except cancelled sessions. Adjacent sessions are permitted. Updates require `appointment_id` and `expected_version` from the last read; stale versions fail without modifying the record. Cancellation is an update to `status='Cancelled'`.

`Backend.list_appointments(principal, from_at=..., to_at=..., status=None, limit=100, offset=0)` returns sessions starting within a half-open timezone-aware range. It excludes other tenants and cases not assigned to the caller (administrators can view organization cases), bounds page sizes to 200, decrypts only returned titles and records an agenda read audit event.

The SQLite adapter uses an immediate write transaction for atomic conflict checking. The unapplied `postgres_scheduling.sql` blueprint supplies range/exclusion constraints; a PostgreSQL runtime adapter and reviewed policies remain required before multi-host deployment. The service is now exposed through authenticated same-origin API endpoints in `web.py`. The adapter derives `Principal` from a verified session and resolves local date/time in the configured organization timezone. Existing real-patient ingestion restrictions remain in place.

## Shared staff scheduling API, availability and recurrence

`web.py` now exposes same-origin scheduling routes behind Google Workspace OIDC sign-in. `dist/staff.html` uses those routes rather than browser-local appointment storage. See [STAFF_SETUP.md](STAFF_SETUP.md) for local initialization, new Google OAuth client setup, staff-subject mappings and deployment requirements.

`PlanningMixin` adds weekly working-hour windows, time-off blocks, DST-aware local-time validation, finite weekly series, idempotent series creation and atomic edits/cancellations of future scheduled occurrences. SQLite persists these features in the development adapter. `postgres_scheduling.sql` is an unapplied production-table blueprint with case/clinician overlap exclusion constraints and forced RLS; a PostgreSQL runtime adapter and reviewed policies still remain.

Current checks target Python 3.12+. The shared browser fixture uses synthetic provider responses only in the test file; cryptographically signed OIDC response validation has separate tests. No production route permits role selection, arbitrary user headers or test-login bypasses.
