"""Availability and finite recurrence rules using an explicit organization timezone."""
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone, date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc

def aware(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('A timezone offset is required')
    return parsed.astimezone(UTC)

def local_start(day, clock, zone):
    """Reject gaps and ambiguous wall times rather than silently shift a session."""
    naive = datetime.fromisoformat(f'{day}T{clock}')
    if naive.tzinfo is not None or naive.second or naive.microsecond:
        raise ValueError('Use a local date and whole-minute time')
    tz = ZoneInfo(zone)
    candidates = set()
    for fold in (0, 1):
        candidate = naive.replace(tzinfo=tz, fold=fold).astimezone(UTC)
        if candidate.astimezone(tz).replace(tzinfo=None) == naive:
            candidates.add(candidate)
    if len(candidates) != 1:
        raise ValueError('This local time is missing or ambiguous because of daylight saving; choose another time')
    return candidates.pop()

class PlanningMixin:
    def organization_timezone(self, p):
        self._role(p)
        row = self.db.execute('SELECT timezone FROM organization_settings WHERE org_id=?', (p.org_id,)).fetchone()
        return row[0] if row else 'America/New_York'

    def _manage_availability(self, p, clinician_id):
        from core import Denied
        role = self._role(p)
        if role not in ('administrator','supervisor') and not (role == 'clinician' and clinician_id == p.user_id):
            raise Denied('Only supervisors or the clinician can manage availability')
        staff = self.db.execute("SELECT 1 FROM staff WHERE org_id=? AND user_id=? AND active=1 AND role='clinician'", (p.org_id,clinician_id)).fetchone()
        if not staff: raise Denied('Active organization clinician required')

    def _check_availability(self, p, clinician_id, starts_at, ends_at):
        row = self.db.execute('SELECT windows_json FROM clinician_availability WHERE org_id=? AND clinician_id=?', (p.org_id,clinician_id)).fetchone()
        start, end = aware(starts_at), aware(ends_at)
        zone = ZoneInfo(self.organization_timezone(p)); ls, le = start.astimezone(zone), end.astimezone(zone)
        if row:
            windows = json.loads(row[0]); sm=ls.hour*60+ls.minute; em=le.hour*60+le.minute
            if ls.date() != le.date() or em <= sm or not any(w['day']==ls.weekday() and w['start']<=sm and em<=w['end'] for w in windows):
                raise ValueError('Session is outside the therapist working hours')
        if self.db.execute('SELECT 1 FROM time_off WHERE org_id=? AND clinician_id=? AND starts_at<? AND ends_at>? LIMIT 1',(p.org_id,clinician_id,ends_at,starts_at)).fetchone():
            raise ValueError('Therapist has time off during this session')

    def save_availability(self, p, clinician_id, windows):
        self._manage_availability(p,clinician_id)
        if not isinstance(windows,list) or len(windows)>28: raise ValueError('Use at most 28 working-hour windows')
        for w in windows:
            if not isinstance(w,dict) or set(w)!={'day','start','end'} or any(type(w[k]) is not int for k in w) or not 0<=w['day']<=6 or not 0<=w['start']<w['end']<=1440:
                raise ValueError('Invalid working-hour window')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE');self._manage_availability(p,clinician_id)
            self.db.execute('INSERT INTO clinician_availability VALUES(?,?,?) ON CONFLICT(org_id,clinician_id) DO UPDATE SET windows_json=excluded.windows_json',(p.org_id,clinician_id,json.dumps(windows)))
            for a in self.db.execute("SELECT starts_at,ends_at FROM appointments WHERE org_id=? AND clinician_id=? AND status='Scheduled' AND starts_at>=?",(p.org_id,clinician_id,datetime.now(UTC).isoformat())).fetchall():
                self._check_availability(p,clinician_id,a['starts_at'],a['ends_at'])
            self._audit(p,'availability.update',clinician_id)

    def add_time_off(self, p, clinician_id, starts_at, ends_at):
        self._manage_availability(p,clinician_id)
        start,end=aware(starts_at).isoformat(),aware(ends_at).isoformat()
        if start>=end: raise ValueError('Time off must end after it starts')
        tid=str(uuid.uuid4())
        with self.db:
            self.db.execute('BEGIN IMMEDIATE');self._manage_availability(p,clinician_id)
            if self.db.execute("SELECT 1 FROM appointments WHERE org_id=? AND clinician_id=? AND status='Scheduled' AND starts_at<? AND ends_at>?",(p.org_id,clinician_id,end,start)).fetchone():
                raise ValueError('Reschedule or cancel overlapping sessions before adding time off')
            self.db.execute('INSERT INTO time_off VALUES(?,?,?,?,?)',(tid,p.org_id,clinician_id,start,end));self._audit(p,'time_off.create',tid)
        return tid

    def remove_time_off(self,p,time_off_id):
        from core import Denied
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row=self.db.execute('SELECT clinician_id FROM time_off WHERE org_id=? AND id=?',(p.org_id,time_off_id)).fetchone()
            if not row: raise Denied('Time off unavailable')
            self._manage_availability(p,row[0]);self.db.execute('DELETE FROM time_off WHERE org_id=? AND id=?',(p.org_id,time_off_id));self._audit(p,'time_off.remove',time_off_id)

    def create_series(self,p,case_id,clinician_id,title,first_date,clock,duration,location,interval_weeks,count,request_key):
        from core import utcnow
        if type(count) is not int or not 2<=count<=26 or type(interval_weeks) is not int or not 1<=interval_weeks<=4:
            raise ValueError('Repeat 2–26 times, every 1–4 weeks')
        if not isinstance(request_key,str) or not 8<=len(request_key)<=120: raise ValueError('An idempotency key is required')
        zone=self.organization_timezone(p)
        if not isinstance(first_date,str):raise ValueError('Use a valid first date')
        first=date.fromisoformat(first_date)
        values=[case_id,clinician_id,title,first_date,clock,duration,location,interval_weeks,count,zone]
        digest=hashlib.sha256(json.dumps(values,separators=(',',':')).encode()).hexdigest()
        sid=str(uuid.uuid4());results=[]
        with self.db:
            self.db.execute('BEGIN IMMEDIATE');self._allowed(p,'schedule',case_id)
            prior=self.db.execute('SELECT id,request_digest FROM appointment_series WHERE org_id=? AND request_key=?',(p.org_id,request_key)).fetchone()
            if prior:
                if prior['request_digest']!=digest: raise ValueError('Idempotency key was used for a different series')
                return {'series_id':prior['id'],'replayed':True}
            self.db.execute('INSERT INTO appointment_series VALUES(?,?,?,?,?,?,?)',(sid,p.org_id,request_key,digest,zone,interval_weeks,utcnow()))
            for index in range(count):
                day=(first+timedelta(weeks=interval_weeks*index)).isoformat()
                start=local_start(day,clock,zone).isoformat()
                a=self._write_appointment(p,case_id,clinician_id,title,start,duration,location,'Scheduled')
                self.db.execute('INSERT INTO series_members VALUES(?,?,?)',(sid,a['id'],day));results.append(a['id'])
            self._audit(p,'series.create',sid)
        return {'series_id':sid,'appointment_ids':results,'replayed':False}

    def update_series_future(self,p,appointment_id,expected_version,*,status=None,clock=None,duration=None,location=None):
        """Edit existing future occurrences atomically; never regenerate cancellations."""
        from core import Denied
        if status not in (None,'Cancelled') or (status is None and all(v is None for v in (clock,duration,location))): raise ValueError('Choose cancellation or a scheduling change')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            base=self.db.execute('''SELECT a.*,m.series_id,m.occurrence_date FROM appointments a JOIN series_members m ON m.appointment_id=a.id WHERE a.org_id=? AND a.id=?''',(p.org_id,appointment_id)).fetchone()
            if not base: raise Denied('Recurring session unavailable')
            self._allowed(p,'schedule',base['case_id'])
            if type(expected_version) is not int or base['version']!=expected_version: raise ValueError('Session changed; reload before saving')
            rows=self.db.execute('''SELECT a.*,m.occurrence_date FROM appointments a JOIN series_members m ON m.appointment_id=a.id WHERE a.org_id=? AND m.series_id=? AND m.occurrence_date>=? ORDER BY m.occurrence_date''',(p.org_id,base['series_id'],base['occurrence_date'])).fetchall()
            zone=self.db.execute('SELECT timezone FROM appointment_series WHERE id=?',(base['series_id'],)).fetchone()[0]
            targets=[a for a in rows if a['status']=='Scheduled']
            # Free the old slots inside this transaction before validating the new set.
            for a in targets:self.db.execute("UPDATE appointments SET status='Cancelled' WHERE id=?",(a['id'],))
            for a in targets:
                title=self.vault.open(a['encrypted_title'],f"{p.org_id}/{a['id']}/appointment").decode()
                start=local_start(a['occurrence_date'],clock,zone).isoformat() if clock else a['starts_at']
                length=duration if duration is not None else int((aware(a['ends_at'])-aware(a['starts_at'])).total_seconds()/60)
                self._write_appointment(p,a['case_id'],a['clinician_id'],title,start,length,location or a['location'],status or 'Scheduled',appointment_id=a['id'],expected_version=a['version'])
            self._audit(p,'series.cancel_future' if status else 'series.update_future',base['series_id'])
        return {'updated':len(targets)}
