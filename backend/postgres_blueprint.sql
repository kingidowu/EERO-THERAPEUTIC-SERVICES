-- Production database blueprint, NOT applied or integration-tested.
-- Run only in a reviewed environment with a separate migration owner.
-- Application role must be NOSUPERUSER NOBYPASSRLS and must not own these tables.
BEGIN;
CREATE SCHEMA IF NOT EXISTS eero;
CREATE TABLE eero.organizations(id uuid PRIMARY KEY,name text NOT NULL);
CREATE TABLE eero.staff(organization_id uuid NOT NULL REFERENCES eero.organizations,id uuid NOT NULL,identity_subject text NOT NULL,role text NOT NULL CHECK(role IN ('administrator','supervisor','clinician','intake','billing')),active boolean NOT NULL DEFAULT true,PRIMARY KEY(organization_id,id),UNIQUE(organization_id,identity_subject));
CREATE TABLE eero.clients(organization_id uuid NOT NULL REFERENCES eero.organizations,id uuid NOT NULL,demographics_ciphertext bytea NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),PRIMARY KEY(organization_id,id));
CREATE TABLE eero.guardian_relationships(organization_id uuid NOT NULL,id uuid NOT NULL,client_id uuid NOT NULL,evidence_ciphertext bytea NOT NULL,valid_until date,revoked_at timestamptz,PRIMARY KEY(organization_id,id),FOREIGN KEY(organization_id,client_id) REFERENCES eero.clients);
CREATE TABLE eero.cases(organization_id uuid NOT NULL,id uuid NOT NULL,client_id uuid NOT NULL,label_ciphertext bytea NOT NULL,status text NOT NULL CHECK(status IN ('active','closed','pending')),created_at timestamptz NOT NULL DEFAULT now(),PRIMARY KEY(organization_id,id),FOREIGN KEY(organization_id,client_id) REFERENCES eero.clients);
CREATE TABLE eero.case_assignments(organization_id uuid NOT NULL,case_id uuid NOT NULL,staff_id uuid NOT NULL,revoked_at timestamptz,PRIMARY KEY(organization_id,case_id,staff_id),FOREIGN KEY(organization_id,case_id) REFERENCES eero.cases,FOREIGN KEY(organization_id,staff_id) REFERENCES eero.staff);
CREATE TABLE eero.documents(organization_id uuid NOT NULL,id uuid NOT NULL,case_id uuid NOT NULL,metadata_ciphertext bytea NOT NULL,created_by uuid NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),PRIMARY KEY(organization_id,id),FOREIGN KEY(organization_id,case_id) REFERENCES eero.cases,FOREIGN KEY(organization_id,created_by) REFERENCES eero.staff);
CREATE TABLE eero.document_versions(organization_id uuid NOT NULL,id uuid NOT NULL,document_id uuid NOT NULL,version_number integer NOT NULL CHECK(version_number>0),opaque_object_key text NOT NULL,sha256 char(64) NOT NULL,size_bytes bigint NOT NULL CHECK(size_bytes>0),scan_state text NOT NULL CHECK(scan_state IN ('quarantined','clean','rejected')),review_state text NOT NULL CHECK(review_state IN ('needs_review','approved','superseded')),created_by uuid NOT NULL,approved_by uuid,created_at timestamptz NOT NULL DEFAULT now(),PRIMARY KEY(organization_id,id),UNIQUE(organization_id,document_id,version_number),FOREIGN KEY(organization_id,document_id) REFERENCES eero.documents,FOREIGN KEY(organization_id,created_by) REFERENCES eero.staff,FOREIGN KEY(organization_id,approved_by) REFERENCES eero.staff,CHECK(approved_by IS NULL OR approved_by<>created_by),CHECK(review_state<>'approved' OR (approved_by IS NOT NULL AND scan_state='clean')));
CREATE TABLE eero.encounters(organization_id uuid NOT NULL,id uuid NOT NULL,case_id uuid NOT NULL,clinician_id uuid NOT NULL,start_at timestamptz NOT NULL,end_at timestamptz,service_code text NOT NULL,PRIMARY KEY(organization_id,id),FOREIGN KEY(organization_id,case_id) REFERENCES eero.cases,FOREIGN KEY(organization_id,clinician_id) REFERENCES eero.staff,CHECK(end_at IS NULL OR end_at>=start_at));
CREATE TABLE eero.progress_notes(organization_id uuid NOT NULL,id uuid NOT NULL,encounter_id uuid NOT NULL,author_id uuid NOT NULL,version_number integer NOT NULL CHECK(version_number>0),body_ciphertext bytea NOT NULL,signed_at timestamptz,supersedes_id uuid,PRIMARY KEY(organization_id,id),FOREIGN KEY(organization_id,encounter_id) REFERENCES eero.encounters,FOREIGN KEY(organization_id,author_id) REFERENCES eero.staff,FOREIGN KEY(organization_id,supersedes_id) REFERENCES eero.progress_notes);
CREATE TABLE eero.psychotherapy_notes(organization_id uuid NOT NULL,id uuid NOT NULL,case_id uuid NOT NULL,author_id uuid NOT NULL,body_ciphertext bytea NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),PRIMARY KEY(organization_id,id),FOREIGN KEY(organization_id,case_id) REFERENCES eero.cases,FOREIGN KEY(organization_id,author_id) REFERENCES eero.staff);
CREATE TABLE eero.service_authorizations(organization_id uuid NOT NULL,id uuid NOT NULL,case_id uuid NOT NULL,evidence_version_id uuid NOT NULL,details_ciphertext bytea NOT NULL,expires_on date,revoked_at timestamptz,PRIMARY KEY(organization_id,id),FOREIGN KEY(organization_id,case_id) REFERENCES eero.cases,FOREIGN KEY(organization_id,evidence_version_id) REFERENCES eero.document_versions);
CREATE TABLE eero.programs(organization_id uuid NOT NULL REFERENCES eero.organizations,id uuid NOT NULL,name text NOT NULL,description text NOT NULL,PRIMARY KEY(organization_id,id));
CREATE TABLE eero.enrollments(organization_id uuid NOT NULL,id uuid NOT NULL,program_id uuid NOT NULL,case_id uuid NOT NULL,status text NOT NULL,PRIMARY KEY(organization_id,id),FOREIGN KEY(organization_id,program_id) REFERENCES eero.programs,FOREIGN KEY(organization_id,case_id) REFERENCES eero.cases);
CREATE TABLE eero.tasks(organization_id uuid NOT NULL,id uuid NOT NULL,case_id uuid NOT NULL,assigned_staff_id uuid NOT NULL,title_ciphertext bytea NOT NULL,due_at timestamptz NOT NULL,completed_at timestamptz,PRIMARY KEY(organization_id,id),FOREIGN KEY(organization_id,case_id) REFERENCES eero.cases,FOREIGN KEY(organization_id,assigned_staff_id) REFERENCES eero.staff);
CREATE TABLE eero.audit_events(id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,organization_id uuid NOT NULL REFERENCES eero.organizations,actor_id uuid NOT NULL,action text NOT NULL,resource_id uuid NOT NULL,occurred_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX ON eero.cases(organization_id,created_at,id);
CREATE INDEX ON eero.documents(organization_id,case_id,created_at,id);
CREATE INDEX ON eero.tasks(organization_id,due_at) WHERE completed_at IS NULL;
CREATE INDEX ON eero.service_authorizations(organization_id,expires_on) WHERE revoked_at IS NULL;
CREATE INDEX ON eero.audit_events(organization_id,occurred_at,id);
-- Fail closed: FORCE RLS with no permissive policy prevents all application-role
-- access until reviewed policies and authenticated tenant/staff session handling exist.
-- Do not add a broad USING(true) policy to get the application running.
DO $$ DECLARE table_name text; BEGIN
 FOR table_name IN SELECT tablename FROM pg_tables WHERE schemaname='eero' LOOP
  EXECUTE format('ALTER TABLE eero.%I ENABLE ROW LEVEL SECURITY',table_name);
  EXECUTE format('ALTER TABLE eero.%I FORCE ROW LEVEL SECURITY',table_name);
 END LOOP;
END $$;
-- Additional required migrations: per-case/role policies, author-only psychotherapy
-- policy, immutable signed-note/audit triggers, authorization purpose/recipient scopes,
-- amendment/disclosure workflows, retention and queue records. Not implemented here.
COMMIT;
