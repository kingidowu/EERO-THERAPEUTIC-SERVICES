-- Unapplied scheduling migration for the production eero schema.
-- Apply after postgres_blueprint.sql with a migration owner. Runtime adapter and
-- reviewed tenant/case RLS policies remain required; these tables fail closed.
BEGIN;
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE TABLE eero.organization_schedule_settings(
 organization_id uuid PRIMARY KEY REFERENCES eero.organizations,
 timezone text NOT NULL
);
CREATE TABLE eero.appointment_series(
 organization_id uuid NOT NULL REFERENCES eero.organizations,id uuid NOT NULL,
 request_key text NOT NULL,request_digest char(64) NOT NULL,timezone text NOT NULL,
 interval_weeks integer NOT NULL CHECK(interval_weeks BETWEEN 1 AND 4),
 created_at timestamptz NOT NULL DEFAULT now(),PRIMARY KEY(organization_id,id),
 UNIQUE(organization_id,request_key)
);
CREATE TABLE eero.appointments(
 organization_id uuid NOT NULL,id uuid NOT NULL,case_id uuid NOT NULL,clinician_id uuid NOT NULL,
 title_ciphertext bytea NOT NULL,starts_at timestamptz NOT NULL,ends_at timestamptz NOT NULL,
 location text NOT NULL CHECK(location IN ('Office','Virtual','In home','In community')),
 status text NOT NULL CHECK(status IN ('Scheduled','Completed','Cancelled','No-show')),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),PRIMARY KEY(organization_id,id),
 FOREIGN KEY(organization_id,case_id) REFERENCES eero.cases,
 FOREIGN KEY(organization_id,clinician_id) REFERENCES eero.staff,
 CHECK(ends_at-starts_at BETWEEN interval '15 minutes' AND interval '240 minutes'),
 EXCLUDE USING gist(organization_id WITH =,clinician_id WITH =,tstzrange(starts_at,ends_at,'[)') WITH &&) WHERE(status<>'Cancelled'),
 EXCLUDE USING gist(organization_id WITH =,case_id WITH =,tstzrange(starts_at,ends_at,'[)') WITH &&) WHERE(status<>'Cancelled')
);
CREATE TABLE eero.series_members(
 organization_id uuid NOT NULL,series_id uuid NOT NULL,appointment_id uuid NOT NULL,occurrence_date date NOT NULL,
 PRIMARY KEY(organization_id,appointment_id),FOREIGN KEY(organization_id,series_id) REFERENCES eero.appointment_series,
 FOREIGN KEY(organization_id,appointment_id) REFERENCES eero.appointments
);
CREATE TABLE eero.clinician_availability(
 organization_id uuid NOT NULL,clinician_id uuid NOT NULL,windows jsonb NOT NULL CHECK(jsonb_typeof(windows)='array'),
 PRIMARY KEY(organization_id,clinician_id),FOREIGN KEY(organization_id,clinician_id) REFERENCES eero.staff
);
CREATE TABLE eero.time_off(
 organization_id uuid NOT NULL,id uuid NOT NULL,clinician_id uuid NOT NULL,starts_at timestamptz NOT NULL,ends_at timestamptz NOT NULL,
 PRIMARY KEY(organization_id,id),FOREIGN KEY(organization_id,clinician_id) REFERENCES eero.staff,CHECK(ends_at>starts_at)
);
CREATE TABLE eero.web_sessions(
 token_hash char(64) PRIMARY KEY,organization_id uuid NOT NULL,staff_id uuid NOT NULL,expires_at timestamptz NOT NULL,
 FOREIGN KEY(organization_id,staff_id) REFERENCES eero.staff
);
CREATE INDEX ON eero.appointments(organization_id,starts_at,id);
CREATE INDEX ON eero.time_off(organization_id,clinician_id,starts_at,ends_at);
CREATE INDEX ON eero.web_sessions(expires_at);
-- Cross-table time-off/appointment checks and availability changes require a
-- shared clinician-row lock in the future PostgreSQL service transaction.
-- Exclusion constraints above protect case/clinician appointment overlaps
-- even if multiple application workers attempt conflicting writes.
DO $$ DECLARE relation text; BEGIN
 FOREACH relation IN ARRAY ARRAY['organization_schedule_settings','appointment_series','appointments','series_members','clinician_availability','time_off','web_sessions'] LOOP
  EXECUTE format('ALTER TABLE eero.%I ENABLE ROW LEVEL SECURITY',relation);
  EXECUTE format('ALTER TABLE eero.%I FORCE ROW LEVEL SECURITY',relation);
 END LOOP;
END $$;
COMMIT;
