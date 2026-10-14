-- Unapplied operations migration after postgres_blueprint.sql and
-- postgres_scheduling.sql. Reviewed policies and a PostgreSQL runtime adapter
-- are still required. Application roles must not own these tables.
BEGIN;
ALTER TABLE eero.tasks
 ADD COLUMN priority text NOT NULL DEFAULT 'Normal' CHECK(priority IN ('High','Normal','Low')),
 ADD COLUMN version integer NOT NULL DEFAULT 1 CHECK(version>0),
 ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();
CREATE TABLE eero.waitlist(
 organization_id uuid NOT NULL,id uuid NOT NULL,case_id uuid NOT NULL,
 service_ciphertext bytea NOT NULL,not_before date NOT NULL,
 priority text NOT NULL CHECK(priority IN ('High','Normal','Low')),
 status text NOT NULL CHECK(status IN ('Waiting','Offered','Booked','Withdrawn')),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),
 clinician_id uuid,offer_title_ciphertext bytea,starts_at timestamptz,ends_at timestamptz,
 location text CHECK(location IN ('Office','Virtual','In home','In community')),
 expires_at timestamptz,appointment_id uuid,
 PRIMARY KEY(organization_id,id),FOREIGN KEY(organization_id,case_id) REFERENCES eero.cases,
 FOREIGN KEY(organization_id,clinician_id) REFERENCES eero.staff,
 FOREIGN KEY(organization_id,appointment_id) REFERENCES eero.appointments,
 CHECK(status<>'Offered' OR (clinician_id IS NOT NULL AND offer_title_ciphertext IS NOT NULL AND starts_at IS NOT NULL AND ends_at IS NOT NULL AND location IS NOT NULL AND expires_at IS NOT NULL)),
 CHECK(status<>'Booked' OR appointment_id IS NOT NULL),
 CHECK(ends_at IS NULL OR ends_at>starts_at)
);
CREATE UNIQUE INDEX waitlist_active_case ON eero.waitlist(organization_id,case_id) WHERE status IN ('Waiting','Offered');
CREATE INDEX ON eero.waitlist(organization_id,status,created_at,id);
ALTER TABLE eero.waitlist ENABLE ROW LEVEL SECURITY;
ALTER TABLE eero.waitlist FORCE ROW LEVEL SECURITY;
-- Booking requires row-locking the waitlist entry, then creating the appointment
-- and closing the entry in one service transaction. Retried bookings return the
-- existing appointment. Offers deliberately do not create slot reservations.
-- Task mutations compare expected version; due dates map to the organization
-- timezone when adapting the SQLite date-only field to PostgreSQL due_at.
COMMIT;
