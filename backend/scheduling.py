"""Authorized scheduling service for fictional data, used by the authenticated web adapter."""
from datetime import datetime, timedelta, timezone
import uuid

STATUSES = ('Scheduled', 'Completed', 'Cancelled', 'No-show')
LOCATIONS = ('In community', 'In home', 'Office', 'Virtual')

class SchedulingMixin:
    def _schedule_values(self, p, case_id, clinician_id, title, starts_at, duration, location, status, *, historical_cancellation=False):
        from core import Denied
        if not isinstance(case_id,str) or not case_id:raise ValueError('Choose a case folder')
        self._allowed(p, 'schedule', case_id)
        if status=='Scheduled' and self.db.execute('SELECT status FROM cases WHERE org_id=? AND id=?',(p.org_id,case_id)).fetchone()['status']=='closed':raise ValueError('Reopen the case before scheduling a session')
        clinician = self.db.execute('SELECT role FROM staff WHERE org_id=? AND user_id=? AND active=1', (p.org_id, clinician_id)).fetchone()
        assigned = self.db.execute('SELECT 1 FROM assignments WHERE org_id=? AND case_id=? AND user_id=?', (p.org_id, case_id, clinician_id)).fetchone()
        if not historical_cancellation and (not clinician or clinician['role'] != 'clinician' or not assigned):
            raise Denied('An active clinician assigned to this case is required')
        if not isinstance(title, str) or not title.strip() or len(title) > 120:
            raise ValueError('Session title must have 1–120 characters')
        if type(duration) is not int or not 15 <= duration <= 240:
            raise ValueError('Duration must be 15–240 minutes')
        if location not in LOCATIONS or status not in STATUSES:
            raise ValueError('Invalid location or session status')
        start = datetime.fromisoformat(starts_at.replace('Z', '+00:00'))
        if start.tzinfo is None or start.utcoffset() is None:
            raise ValueError('Session start must include a timezone offset')
        start = start.astimezone(timezone.utc)
        if start.second or start.microsecond:
            raise ValueError('Session start must use whole minutes')
        return title.strip(), start.isoformat(), (start + timedelta(minutes=duration)).isoformat()

    def _schedule_conflict(self, p, case_id, clinician_id, starts_at, ends_at, exclude=''):
        row = self.db.execute("SELECT 1 FROM appointments WHERE org_id=? AND id<>? AND status<>'Cancelled' AND (case_id=? OR clinician_id=?) AND starts_at<? AND ends_at>? LIMIT 1", (p.org_id, exclude, case_id, clinician_id, ends_at, starts_at)).fetchone()
        if row:
            raise ValueError('This case or clinician already has an overlapping session')

    def save_appointment(self, p, case_id, clinician_id, title, starts_at, duration=60,
                         location='Office', status='Scheduled', *, appointment_id=None, expected_version=None):
        """Create or replace a session. Updates require a version to prevent lost edits."""
        from core import Denied, utcnow
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            return self._write_appointment(p,case_id,clinician_id,title,starts_at,duration,location,status,
                                           appointment_id=appointment_id,expected_version=expected_version)

    def _write_appointment(self,p,case_id,clinician_id,title,starts_at,duration,location,status,*,appointment_id=None,expected_version=None):
        from core import Denied, utcnow
        aid = appointment_id or str(uuid.uuid4())
        now = utcnow()
        existing = self.db.execute('SELECT * FROM appointments WHERE org_id=? AND id=?', (p.org_id, aid)).fetchone()
        if appointment_id:
            if not existing:
                raise Denied('Session unavailable')
            self._allowed(p, 'schedule', existing['case_id'])
            if type(expected_version) is not int or existing['version'] != expected_version:
                raise ValueError('Session changed; reload before saving')
        historical_cancellation=bool(existing and status=='Cancelled' and existing['case_id']==case_id and existing['clinician_id']==clinician_id)
        title, start, end = self._schedule_values(p, case_id, clinician_id, title, starts_at, duration, location, status,historical_cancellation=historical_cancellation)
        if status == 'Scheduled':
            self._check_availability(p,clinician_id,start,end)
        if status != 'Cancelled':
            self._schedule_conflict(p, case_id, clinician_id, start, end, aid)
        encrypted = self.vault.seal(title.encode(), f'{p.org_id}/{aid}/appointment')
        if existing:
            self.db.execute('UPDATE appointments SET case_id=?,clinician_id=?,encrypted_title=?,starts_at=?,ends_at=?,location=?,status=?,version=version+1,updated_at=? WHERE org_id=? AND id=?', (case_id, clinician_id, encrypted, start, end, location, status, now, p.org_id, aid))
        else:
            self.db.execute('INSERT INTO appointments(id,org_id,case_id,clinician_id,encrypted_title,starts_at,ends_at,location,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)', (aid,p.org_id,case_id,clinician_id,encrypted,start,end,location,status,now,now))
        self._audit(p, 'appointment.update' if existing else 'appointment.create', aid)
        return {'id': aid, 'version': existing['version'] + 1 if existing else 1}

    def list_appointments(self, p, *, from_at, to_at, status=None, limit=100, offset=0):
        """Bounded agenda, scoped to tenant and the caller's case assignments."""
        from core import Denied
        role = self._role(p)
        if role not in ('administrator', 'supervisor', 'clinician', 'intake'):
            raise Denied('Permission denied')
        bounds = []
        for value in (from_at, to_at):
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError('Agenda bounds require timezone offsets')
            bounds.append(parsed.astimezone(timezone.utc).isoformat())
        if bounds[0] >= bounds[1] or (status is not None and status not in STATUSES):
            raise ValueError('Invalid agenda range or status')
        if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or offset < 0:
            raise ValueError('Invalid pagination')
        rows = self.db.execute('''SELECT a.*,m.series_id,m.occurrence_date FROM appointments a LEFT JOIN series_members m ON m.appointment_id=a.id
            WHERE a.org_id=? AND a.starts_at>=? AND a.starts_at<?
            AND (? IS NULL OR a.status=?)
            AND (?='administrator' OR EXISTS(SELECT 1 FROM assignments x
                WHERE x.org_id=a.org_id AND x.case_id=a.case_id AND x.user_id=?))
            ORDER BY a.starts_at,a.id LIMIT ? OFFSET ?''', (p.org_id,*bounds,status,status,role,p.user_id,limit,offset)).fetchall()
        result = []
        for row in rows:
            value = {key: row[key] for key in ('id','case_id','clinician_id','starts_at','ends_at','location','status','version','series_id','occurrence_date')}
            value['title'] = self.vault.open(row['encrypted_title'], f"{p.org_id}/{row['id']}/appointment").decode()
            result.append(value)
        with self.db:
            self._audit(p, 'appointment.agenda.read', 'agenda')
        return result
