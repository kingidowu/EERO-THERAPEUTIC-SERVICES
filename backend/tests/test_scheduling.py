import sqlite3
import tempfile
import unittest
from pathlib import Path
from core import Backend, Principal, Denied

class SchedulingTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.backend = Backend(self.db, b'k'*32)
        with self.db:
            self.db.executemany('INSERT INTO organizations VALUES(?,?)', [('eero','Demo'),('other','Other')])
            self.db.executemany('INSERT INTO staff(org_id,user_id,role) VALUES(?,?,?)', [('eero','admin','administrator'),('eero','c1','clinician'),('eero','c2','clinician'),('eero','intake','intake'),('eero','billing','billing'),('other','admin','administrator')])
        self.admin = Principal('eero','admin')
        self.cid = self.backend.create_case(self.admin,'Sample case')
        for user in ('c1','c2','intake'): self.backend.assign(self.admin,self.cid,user)
    def tearDown(self): self.db.close()
    def save(self, **kw):
        args = dict(case_id=self.cid,clinician_id='c1',title='Fictional coaching',starts_at='2026-10-14T09:00:00-04:00')
        args.update(kw)
        return self.backend.save_appointment(self.admin, **args)
    def agenda(self, p=None, **kw):
        return self.backend.list_appointments(p or self.admin,from_at='2026-10-14T00:00:00-04:00',to_at='2026-10-15T00:00:00-04:00',**kw)
    def test_create_normalizes_timezone_encrypts_title_and_audits(self):
        result=self.save();row=self.agenda()[0]
        self.assertEqual(row['id'],result['id']);self.assertEqual(row['starts_at'],'2026-10-14T13:00:00+00:00')
        self.assertEqual(row['ends_at'],'2026-10-14T14:00:00+00:00');self.assertEqual(row['title'],'Fictional coaching')
        self.assertNotIn('Fictional coaching','\n'.join(self.db.iterdump()))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM audit_events WHERE action LIKE 'appointment.%'").fetchone()[0],2)
    def test_case_overlap_even_with_different_clinician(self):
        self.save()
        with self.assertRaises(ValueError): self.save(clinician_id='c2',starts_at='2026-10-14T09:30:00-04:00')
        self.assertEqual(len(self.agenda()),1)
    def test_clinician_overlap_across_cases_and_timezone_offsets(self):
        self.save();second=self.backend.create_case(self.admin,'Second sample');self.backend.assign(self.admin,second,'c1')
        with self.assertRaises(ValueError): self.save(case_id=second,starts_at='2026-10-14T13:30:00+00:00')
        self.save(case_id=second,starts_at='2026-10-14T10:00:00-04:00')
        self.assertEqual(len(self.agenda()),2)
    def test_cancel_frees_time_and_reinstating_checks_overlap(self):
        a=self.save();updated=self.save(appointment_id=a['id'],expected_version=1,status='Cancelled')
        self.save()
        with self.assertRaises(ValueError): self.save(appointment_id=a['id'],expected_version=updated['version'])
        self.assertEqual(len(self.agenda(status='Cancelled')),1)
    def test_stale_edit_does_not_overwrite_or_add_audit(self):
        a=self.save();self.save(appointment_id=a['id'],expected_version=1,status='Completed')
        before=self.db.execute('SELECT COUNT(*) FROM audit_events').fetchone()[0]
        with self.assertRaises(ValueError): self.save(appointment_id=a['id'],expected_version=1,title='Lost edit')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM audit_events').fetchone()[0],before)
        self.assertEqual(self.agenda()[0]['status'],'Completed')
    def test_agenda_is_tenant_assignment_and_role_scoped(self):
        self.save();second=self.backend.create_case(self.admin,'Private sample');self.backend.assign(self.admin,second,'c2')
        self.save(case_id=second,clinician_id='c2',starts_at='2026-10-14T11:00:00-04:00')
        self.assertEqual(len(self.agenda(Principal('eero','c1'))),1)
        self.assertEqual(self.agenda(Principal('other','admin')),[])
        with self.assertRaises(Denied): self.agenda(Principal('eero','billing'))
        with self.db: self.db.execute("UPDATE staff SET active=0 WHERE user_id='c1'")
        with self.assertRaises(Denied): self.agenda(Principal('eero','c1'))
    def test_unassigned_inactive_and_non_clinicians_rejected(self):
        for uid in ('admin','billing','missing'):
            with self.assertRaises(Denied): self.save(clinician_id=uid)
        with self.db: self.db.execute("UPDATE staff SET active=0 WHERE user_id='c1'")
        with self.assertRaises(Denied): self.save()
    def test_cannot_move_session_from_an_unassigned_case(self):
        second=self.backend.create_case(self.admin,'Other case');self.backend.assign(self.admin,second,'c2')
        a=self.save(case_id=second,clinician_id='c2')
        with self.assertRaises(Denied): self.backend.save_appointment(Principal('eero','c1'),self.cid,'c1','Sample move','2026-10-14T11:00:00-04:00',appointment_id=a['id'],expected_version=1)
    def test_validation_and_pagination(self):
        for values in [dict(starts_at='2026-10-14T09:00:00'),dict(duration=True),dict(duration=5),dict(title=' '),dict(status='Approved'),dict(location='Anywhere')]:
            with self.assertRaises(ValueError): self.save(**values)
        self.save();self.save(starts_at='2026-10-14T10:00:00-04:00')
        self.assertEqual(len(self.agenda(limit=1,offset=1)),1)
        with self.assertRaises(ValueError): self.agenda(limit=201)
    def test_independent_database_connections_observe_conflicts(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'sample.db'
            one=sqlite3.connect(path);self.db.backup(one)
            two=sqlite3.connect(path)
            try:
                b1=Backend(one,b'k'*32);b2=Backend(two,b'k'*32)
                b1.save_appointment(self.admin,self.cid,'c1','Sample','2026-10-14T13:00:00Z')
                with self.assertRaises(ValueError): b2.save_appointment(self.admin,self.cid,'c1','Sample','2026-10-14T13:30:00Z')
            finally: one.close();two.close()

if __name__ == '__main__': unittest.main()
