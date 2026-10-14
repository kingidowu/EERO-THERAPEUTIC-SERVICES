-- Development schema. SQLite is for local validation, not the production medical record store.
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS organizations(id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS staff(org_id TEXT NOT NULL REFERENCES organizations(id), user_id TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('administrator','supervisor','clinician','intake','billing')), active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), PRIMARY KEY(org_id,user_id));
CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY, org_id TEXT NOT NULL REFERENCES organizations(id), encrypted_label BLOB NOT NULL, status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, UNIQUE(org_id,id));
CREATE INDEX IF NOT EXISTS cases_by_org ON cases(org_id,created_at,id);
CREATE TABLE IF NOT EXISTS assignments(org_id TEXT NOT NULL, case_id TEXT NOT NULL, user_id TEXT NOT NULL, PRIMARY KEY(org_id,case_id,user_id), FOREIGN KEY(org_id,case_id) REFERENCES cases(org_id,id), FOREIGN KEY(org_id,user_id) REFERENCES staff(org_id,user_id));
CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, org_id TEXT NOT NULL, case_id TEXT NOT NULL, encrypted_title BLOB NOT NULL, encrypted_content BLOB NOT NULL, digest TEXT NOT NULL, media_type TEXT NOT NULL, scan_state TEXT NOT NULL DEFAULT 'quarantined' CHECK(scan_state IN ('quarantined','clean','rejected')), review_state TEXT NOT NULL DEFAULT 'needs_review' CHECK(review_state IN ('needs_review','approved')), created_by TEXT NOT NULL, reviewed_by TEXT, created_at TEXT NOT NULL, UNIQUE(org_id,id), FOREIGN KEY(org_id,case_id) REFERENCES cases(org_id,id));
CREATE INDEX IF NOT EXISTS documents_by_case ON documents(org_id,case_id,created_at,id);
CREATE TABLE IF NOT EXISTS notes(id TEXT PRIMARY KEY, org_id TEXT NOT NULL, case_id TEXT NOT NULL, author_id TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('progress','psychotherapy')), encrypted_body BLOB NOT NULL, created_at TEXT NOT NULL, FOREIGN KEY(org_id,case_id) REFERENCES cases(org_id,id));
CREATE INDEX IF NOT EXISTS notes_by_case ON notes(org_id,case_id,kind,created_at,id);
CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, org_id TEXT NOT NULL, case_id TEXT NOT NULL, encrypted_title BLOB NOT NULL, due_date TEXT NOT NULL, completed_at TEXT, created_at TEXT NOT NULL, FOREIGN KEY(org_id,case_id) REFERENCES cases(org_id,id));
CREATE INDEX IF NOT EXISTS tasks_due ON tasks(org_id,due_date,completed_at);
CREATE TABLE IF NOT EXISTS authorizations(id TEXT PRIMARY KEY, org_id TEXT NOT NULL, case_id TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('service','disclosure','psychotherapy_disclosure')), evidence_document_id TEXT NOT NULL, expires_on TEXT NOT NULL, revoked_at TEXT, created_at TEXT NOT NULL, FOREIGN KEY(org_id,case_id) REFERENCES cases(org_id,id), FOREIGN KEY(org_id,evidence_document_id) REFERENCES documents(org_id,id));
CREATE INDEX IF NOT EXISTS authorizations_expiry ON authorizations(org_id,expires_on,revoked_at);
CREATE TABLE IF NOT EXISTS audit_events(sequence INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT NOT NULL, user_id TEXT NOT NULL, action TEXT NOT NULL, resource_id TEXT NOT NULL, occurred_at TEXT NOT NULL, previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS audit_by_org ON audit_events(org_id,sequence);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_events BEGIN SELECT RAISE(ABORT,'Audit events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT,'Audit events are append-only'); END;

-- Schedule times are normalized UTC; encrypted titles stay tenant/resource bound.
CREATE TABLE IF NOT EXISTS appointments(
 id TEXT PRIMARY KEY, org_id TEXT NOT NULL, case_id TEXT NOT NULL, clinician_id TEXT NOT NULL,
 encrypted_title BLOB NOT NULL, starts_at TEXT NOT NULL, ends_at TEXT NOT NULL,
 location TEXT NOT NULL CHECK(location IN ('In community','In home','Office','Virtual')),
 status TEXT NOT NULL DEFAULT 'Scheduled' CHECK(status IN ('Scheduled','Completed','Cancelled','No-show')),
 version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 FOREIGN KEY(org_id,case_id) REFERENCES cases(org_id,id),
 FOREIGN KEY(org_id,clinician_id) REFERENCES staff(org_id,user_id)
);
CREATE INDEX IF NOT EXISTS appointments_schedule ON appointments(org_id,clinician_id,starts_at,ends_at);
CREATE INDEX IF NOT EXISTS appointments_case ON appointments(org_id,case_id,starts_at);

CREATE TABLE IF NOT EXISTS organization_settings(org_id TEXT PRIMARY KEY REFERENCES organizations(id), timezone TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS clinician_availability(org_id TEXT NOT NULL, clinician_id TEXT NOT NULL, windows_json TEXT NOT NULL, PRIMARY KEY(org_id,clinician_id), FOREIGN KEY(org_id,clinician_id) REFERENCES staff(org_id,user_id));
CREATE TABLE IF NOT EXISTS time_off(id TEXT PRIMARY KEY,org_id TEXT NOT NULL,clinician_id TEXT NOT NULL,starts_at TEXT NOT NULL,ends_at TEXT NOT NULL,FOREIGN KEY(org_id,clinician_id) REFERENCES staff(org_id,user_id));
CREATE TABLE IF NOT EXISTS appointment_series(id TEXT PRIMARY KEY,org_id TEXT NOT NULL REFERENCES organizations(id),request_key TEXT NOT NULL,request_digest TEXT NOT NULL,timezone TEXT NOT NULL,interval_weeks INTEGER NOT NULL,created_at TEXT NOT NULL,UNIQUE(org_id,request_key));
CREATE TABLE IF NOT EXISTS series_members(series_id TEXT NOT NULL REFERENCES appointment_series(id),appointment_id TEXT PRIMARY KEY REFERENCES appointments(id),occurrence_date TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS staff_identities(issuer TEXT NOT NULL,subject TEXT NOT NULL,org_id TEXT NOT NULL,user_id TEXT NOT NULL,PRIMARY KEY(issuer,subject),FOREIGN KEY(org_id,user_id) REFERENCES staff(org_id,user_id));
CREATE TABLE IF NOT EXISTS web_sessions(token_hash TEXT PRIMARY KEY,org_id TEXT NOT NULL,user_id TEXT NOT NULL,expires_at TEXT NOT NULL,FOREIGN KEY(org_id,user_id) REFERENCES staff(org_id,user_id));
