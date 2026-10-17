import sqlite3,unittest
from datetime import datetime,timedelta,timezone
from core import Backend,Principal,Denied

class OperationsTests(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.b=Backend(self.db,b'k'*32)
  with self.db:
   self.db.executemany('INSERT INTO organizations VALUES(?,?)',[('eero','Sample'),('other','Other')])
   self.db.executemany('INSERT INTO staff(org_id,user_id,role) VALUES(?,?,?)',[('eero','admin','administrator'),('eero','c','clinician'),('eero','intake','intake'),('eero','unassigned','clinician'),('eero','billing','billing'),('other','admin','administrator')])
  self.p=Principal('eero','admin');self.c=Principal('eero','c');self.cid=self.b.create_case(self.p,'Fictional case')
  for uid in ['c','intake']:self.b.assign(self.p,self.cid,uid)
 def tearDown(self):self.db.close()
 def task(self,**kw):
  d=dict(case_id=self.cid,title='Fictional follow-up',due_date='2001-01-01',assigned_user_id='c',priority='High');d.update(kw);return self.b.save_work_task(self.p,**d)
 def queue(self,**kw):
  d=dict(case_id=self.cid,service='Fictional parent coaching',not_before='2099-12-01',priority='Normal');d.update(kw);return self.b.add_waitlist(self.p,**d)
 def offer(self,w,**kw):
  d=dict(clinician_id='c',title='Fictional offered session',starts_at='2099-12-01T09:00:00-05:00',duration=60,location='Office');d.update(kw);return self.b.offer_waitlist(self.p,w['id'],w['version'],**d)
 def test_task_assignment_priority_overdue_and_encryption(self):
  t=self.task();rows=self.b.list_work_tasks(self.c,status='Overdue',assignee='c',priority='High');self.assertEqual(rows[0]['id'],t['id']);self.assertTrue(rows[0]['overdue']);self.assertEqual(rows[0]['assigned_user_id'],'c')
  self.assertNotIn('Fictional follow-up','\n'.join(self.db.iterdump()))
 def test_task_requires_active_assigned_staff_and_case_permission(self):
  for uid in ['unassigned','billing','missing']:
   with self.assertRaises(Denied):self.task(assigned_user_id=uid)
  with self.db:self.db.execute("UPDATE staff SET active=0 WHERE user_id='c'")
  with self.assertRaises(Denied):self.task()
  with self.assertRaises(Denied):self.b.save_work_task(Principal('eero','unassigned'),self.cid,'Sample','2099-01-01','intake')
 def test_task_scope_and_pagination(self):
  self.task();self.task(title='Second sample');self.assertEqual(len(self.b.list_work_tasks(self.c,limit=1,offset=1)),1)
  self.assertEqual(self.b.list_work_tasks(Principal('other','admin')),[]);self.assertEqual(self.b.list_work_tasks(Principal('eero','unassigned')),[])
  with self.assertRaises(Denied):self.b.list_work_tasks(Principal('eero','billing'))
  with self.assertRaises(ValueError):self.b.list_work_tasks(self.p,limit=201)
 def test_task_completion_reopen_and_stale_edit(self):
  t=self.task();done=self.b.set_work_task_state(self.c,t['id'],t['version'],'Done');self.assertEqual(self.b.list_work_tasks(self.c,status='Overdue'),[]);self.assertEqual(len(self.b.list_work_tasks(self.c,status='Done')),1)
  with self.assertRaises(ValueError):self.task(task_id=t['id'],expected_version=t['version'],title='Stale change')
  self.b.set_work_task_state(self.c,t['id'],done['version'],'Open');self.assertEqual(len(self.b.list_work_tasks(self.c,status='Overdue')),1)
 def test_reassignment_and_legacy_adoption(self):
  tid=self.b.create_task(self.p,self.cid,'Legacy sample','2099-12-01');row=self.b.list_work_tasks(self.p)[0];self.assertEqual(row['version'],0)
  with self.assertRaises(ValueError):self.b.set_work_task_state(self.p,tid,0,'Done')
  adopted=self.task(task_id=tid,expected_version=0,assigned_user_id='intake');self.assertEqual(adopted['version'],1)
  self.b.complete_task(self.p,tid)
  with self.assertRaises(ValueError):self.b.set_work_task_state(self.p,tid,1,'Open')
 def test_waitlist_duplicate_and_sensitive_preferences(self):
  self.queue()
  with self.assertRaises(ValueError):self.queue()
  self.assertNotIn('Fictional parent coaching','\n'.join(self.db.iterdump()))
 def test_waitlist_clinician_readonly_and_tenant_case_scope(self):
  w=self.queue();self.assertEqual(len(self.b.list_waitlist(self.c)),1)
  self.assertEqual(self.b.list_waitlist(Principal('eero','unassigned')),[]);self.assertEqual(self.b.list_waitlist(Principal('other','admin')),[])
  with self.assertRaises(Denied):self.b.add_waitlist(self.c,self.cid,'Sample','2099-12-01')
  with self.assertRaises(Denied):self.b.resolve_waitlist(Principal('other','admin'),w['id'],w['version'],'Withdrawn')
 def test_offer_checks_earliest_date_hours_and_time_off(self):
  w=self.queue()
  with self.assertRaises(ValueError):self.offer(w,starts_at='2099-11-30T09:00:00-05:00')
  self.b.save_availability(self.p,'c',[{'day':1,'start':540,'end':1020}])
  with self.assertRaises(ValueError):self.offer(w,starts_at='2099-12-01T08:00:00-05:00')
  self.b.add_time_off(self.p,'c','2099-12-01T09:00:00-05:00','2099-12-01T10:00:00-05:00')
  with self.assertRaises(ValueError):self.offer(w)
  self.assertEqual(self.b.list_waitlist(self.p)[0]['status'],'Waiting')
 def test_offer_does_not_book_or_send_and_has_expiry(self):
  w=self.queue();offer=self.offer(w);self.assertEqual(self.db.execute('SELECT COUNT(*) FROM appointments').fetchone()[0],0)
  row=self.b.list_waitlist(self.p)[0];self.assertEqual(row['status'],'Offered');self.assertFalse(row['expired']);self.assertLess(datetime.fromisoformat(offer['expires_at']),datetime.now(timezone.utc)+timedelta(hours=49))
  self.assertNotIn('Fictional offered session','\n'.join(self.db.iterdump()))
 def test_booking_requires_confirmation_and_current_version(self):
  w=self.queue();o=self.offer(w)
  with self.assertRaises(ValueError):self.b.book_waitlist(self.p,w['id'],o['version'],'')
  with self.assertRaises(ValueError):self.b.book_waitlist(self.p,w['id'],w['version'],'confirmed')
  self.assertEqual(self.db.execute('SELECT COUNT(*) FROM appointments').fetchone()[0],0)
 def test_acceptance_books_atomically_and_retry_does_not_duplicate(self):
  w=self.queue();o=self.offer(w);booked=self.b.book_waitlist(self.p,w['id'],o['version'],'confirmed');retry=self.b.book_waitlist(self.p,w['id'],o['version'],'confirmed')
  self.assertEqual(booked['id'],retry['id']);self.assertTrue(retry['replayed']);self.assertEqual(self.db.execute('SELECT COUNT(*) FROM appointments').fetchone()[0],1);self.assertEqual(self.b.list_waitlist(self.p),[])
  self.assertEqual(self.b.list_waitlist(self.p,status='Booked')[0]['appointment_id'],booked['id'])
 def test_conflict_between_offer_and_acceptance_preserves_offer(self):
  w=self.queue();o=self.offer(w);self.b.save_appointment(self.p,self.cid,'c','Competing sample','2099-12-01T09:30:00-05:00')
  with self.assertRaises(ValueError):self.b.book_waitlist(self.p,w['id'],o['version'],'confirmed')
  self.assertEqual(self.b.list_waitlist(self.p)[0]['status'],'Offered');self.assertEqual(self.db.execute('SELECT COUNT(*) FROM appointments').fetchone()[0],1)
 def test_time_off_after_offer_blocks_acceptance(self):
  w=self.queue();o=self.offer(w);self.b.add_time_off(self.p,'c','2099-12-01T09:00:00-05:00','2099-12-01T12:00:00-05:00')
  with self.assertRaises(ValueError):self.b.book_waitlist(self.p,w['id'],o['version'],'confirmed')
  self.assertEqual(self.db.execute('SELECT COUNT(*) FROM appointments').fetchone()[0],0)
 def test_expired_offer_can_be_returned_to_waiting(self):
  w=self.queue();o=self.offer(w)
  with self.db:self.db.execute("UPDATE waitlist SET expires_at='2000-01-01T00:00:00+00:00'")
  self.assertTrue(self.b.list_waitlist(self.p)[0]['expired'])
  with self.assertRaises(ValueError):self.b.book_waitlist(self.p,w['id'],o['version'],'confirmed')
  new=self.b.resolve_waitlist(self.p,w['id'],o['version'],'Declined');self.assertEqual(self.b.list_waitlist(self.p)[0]['status'],'Waiting');self.offer({'id':w['id'],'version':new['version']})
 def test_withdrawal_allows_new_request_and_stale_offer_rejected(self):
  w=self.queue();self.b.resolve_waitlist(self.p,w['id'],1,'Withdrawn');self.queue()
  with self.assertRaises(ValueError):self.offer(w)
  self.assertEqual(len(self.b.list_waitlist(self.p,status='All')),2)
 def test_priority_and_status_filters_and_invalid_values(self):
  w=self.queue();second=self.b.create_case(self.p,'Second case');self.b.assign(self.p,second,'c');high=self.queue(case_id=second,priority='High');self.assertEqual(self.b.list_waitlist(self.p)[0]['id'],high['id'])
  for kwargs in [dict(priority='Critical'),dict(not_before='bad'),dict(service=' ')]:
   with self.assertRaises(ValueError):self.queue(case_id=second,**kwargs)
  with self.assertRaises(ValueError):self.b.list_waitlist(self.p,status='Unknown')
