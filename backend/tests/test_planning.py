import sqlite3,unittest
from core import Backend,Principal,Denied
from planning import local_start
class PlanningTests(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.b=Backend(self.db,b'k'*32)
  with self.db:
   self.db.execute("INSERT INTO organizations VALUES('eero','Sample')")
   self.db.executemany('INSERT INTO staff(org_id,user_id,role) VALUES(?,?,?)',[('eero','admin','administrator'),('eero','c','clinician'),('eero','other','clinician'),('eero','intake','intake')])
  self.p=Principal('eero','admin');self.cid=self.b.create_case(self.p,'Sample');self.b.assign(self.p,self.cid,'c')
 def tearDown(self):self.db.close()
 def save(self,start='2099-12-01T09:00:00-05:00',**kw):return self.b.save_appointment(self.p,self.cid,'c','Sample',start,**kw)
 def series(self,**kw):
  args=dict(case_id=self.cid,clinician_id='c',title='Weekly sample',first_date='2026-10-26',clock='09:00',duration=60,location='Office',interval_weeks=1,count=3,request_key='sample-request');args.update(kw);return self.b.create_series(self.p,**args)
 def rows(self):return self.b.list_appointments(self.p,from_at='2026-01-01T00:00:00Z',to_at='2100-01-01T00:00:00Z')
 def test_hours_and_outside_hours_and_no_hours(self):
  self.b.save_availability(self.p,'c',[{'day':1,'start':540,'end':1020}]);self.save()
  for start in ['2099-12-01T08:00:00-05:00','2099-12-02T09:00:00-05:00']:
   with self.assertRaises(ValueError):self.save(start)
  with self.assertRaises(ValueError):self.b.save_availability(self.p,'c',[])
  self.assertEqual(len(self.rows()),1)
 def test_clinician_own_hours_only(self):
  self.b.save_availability(Principal('eero','c'),'c',[])
  for user in ['other','intake']:
   with self.assertRaises(Denied):self.b.save_availability(Principal('eero',user),'c',[])
  with self.assertRaises(ValueError):self.save()
 def test_time_off_and_remove(self):
  tid=self.b.add_time_off(self.p,'c','2099-12-01T08:00:00-05:00','2099-12-01T10:00:00-05:00')
  with self.assertRaises(ValueError):self.save()
  with self.assertRaises(Denied):self.b.remove_time_off(Principal('eero','other'),tid)
  self.b.remove_time_off(self.p,tid);self.save()
 def test_time_off_cannot_silently_overlap_booked_session(self):
  self.save()
  with self.assertRaises(ValueError):self.b.add_time_off(self.p,'c','2099-12-01T09:00:00-05:00','2099-12-01T12:00:00-05:00')
  self.assertEqual(self.db.execute('SELECT COUNT(*) FROM time_off').fetchone()[0],0)
 def test_weekly_wall_time_across_dst(self):
  self.series();self.assertEqual([r['starts_at'] for r in self.rows()],['2026-10-26T13:00:00+00:00','2026-11-02T14:00:00+00:00','2026-11-09T14:00:00+00:00'])
 def test_missing_and_ambiguous_local_time(self):
  for day,clock in [('2026-03-08','02:30'),('2026-11-01','01:30')]:
   with self.assertRaises(ValueError):local_start(day,clock,'America/New_York')
 def test_series_conflict_rolls_back_everything(self):
  self.save('2026-11-02T09:30:00-05:00')
  with self.assertRaises(ValueError):self.series()
  self.assertEqual(len(self.rows()),1);self.assertEqual(self.db.execute('SELECT COUNT(*) FROM appointment_series').fetchone()[0],0)
 def test_idempotency_preserves_cancellation(self):
  self.series();first=self.rows()[0];self.b.update_series_future(self.p,first['id'],first['version'],status='Cancelled')
  self.assertTrue(self.series()['replayed']);self.assertEqual(len(self.rows()),3);self.assertTrue(all(r['status']=='Cancelled' for r in self.rows()))
  with self.assertRaises(ValueError):self.series(count=4)
 def test_individual_exception_and_future_edit(self):
  self.series();rows=self.rows();a=rows[1]
  self.b.save_appointment(self.p,self.cid,'c',a['title'],a['starts_at'],status='Cancelled',appointment_id=a['id'],expected_version=a['version'])
  a=rows[2];self.b.update_series_future(self.p,a['id'],a['version'],clock='11:00',duration=45)
  after=self.rows();self.assertEqual(after[0]['starts_at'],rows[0]['starts_at']);self.assertEqual(after[1]['status'],'Cancelled');self.assertEqual(after[2]['starts_at'],'2026-11-09T16:00:00+00:00')
 def test_future_conflict_rolls_back_all_edits(self):
  self.series();first=self.rows()[0];self.save('2026-11-09T11:00:00-05:00');before=self.rows()
  with self.assertRaises(ValueError):self.b.update_series_future(self.p,first['id'],first['version'],clock='11:00')
  self.assertEqual(before,self.rows())
 def test_invalid_recurrence_bounds(self):
  for kw in [dict(count=27),dict(count=True),dict(interval_weeks=0),dict(request_key='tiny')]:
   with self.assertRaises(ValueError):self.series(**kw)
