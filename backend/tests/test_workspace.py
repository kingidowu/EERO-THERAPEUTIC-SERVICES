import unittest
import test_operations
from core import Principal,Denied

class WorkspaceTests(unittest.TestCase):
 setUp=test_operations.OperationsTests.setUp
 tearDown=test_operations.OperationsTests.tearDown
 def test_case_lifecycle_version_encryption_and_closed_guards(self):
  created=self.b.create_workspace_case(self.p,'New fictional case');cid=created['id']
  self.assertEqual(created['version'],1)
  self.assertNotIn('New fictional case','\n'.join(self.db.iterdump()))
  self.b.update_workspace_case(self.p,cid,1,'Renamed fictional case','closed')
  with self.assertRaises(ValueError):self.b.update_workspace_case(self.p,cid,1,'Stale','active')
  self.b.assign(self.p,cid,'c')
  with self.assertRaises(ValueError):self.b.save_appointment(self.p,cid,'c','Sample','2099-12-01T09:00:00-05:00')
  with self.assertRaises(ValueError):self.b.add_waitlist(self.p,cid,'Sample','2099-12-01')
  with self.assertRaises(ValueError):self.b.save_work_task(self.p,cid,'Sample','2099-12-01','c')
  self.b.update_workspace_case(self.p,cid,2,'Reopened','active')
 def test_assignment_scope_version_and_removal_guards(self):
  cid=self.b.create_workspace_case(self.p,'Team sample')['id']
  self.b.update_case_assignment(self.p,cid,1,'c','Assign')
  with self.assertRaises(ValueError):self.b.update_case_assignment(self.p,cid,1,'c','Remove')
  with self.assertRaises(Denied):self.b.update_case_assignment(self.c,cid,2,'admin','Remove')
  task=self.b.save_work_task(self.p,cid,'Sample','2099-12-01','c')
  with self.assertRaises(ValueError):self.b.update_case_assignment(self.p,cid,2,'c','Remove')
  with self.assertRaises(ValueError):self.b.update_workspace_case(self.p,cid,2,'Sample','closed')
  self.b.set_work_task_state(self.p,task['id'],1,'Done')
  self.b.update_case_assignment(self.p,cid,2,'c','Remove')
  self.b.update_workspace_case(self.p,cid,3,'Sample','closed')
  with self.assertRaises(ValueError):self.b.set_work_task_state(self.p,task['id'],2,'Open')
 def test_inactive_clinician_session_can_be_cancelled_only_as_existing(self):
  session=self.b.save_appointment(self.p,self.cid,'c','Sample','2099-12-01T09:00:00-05:00')
  with self.db:self.db.execute("UPDATE staff SET active=0 WHERE user_id='c'")
  self.b.save_appointment(self.p,self.cid,'c','Sample','2099-12-01T09:00:00-05:00',status='Cancelled',appointment_id=session['id'],expected_version=1)
  with self.assertRaises(Denied):self.b.save_appointment(self.p,self.cid,'c','Sample','2099-12-01T09:00:00-05:00',status='Cancelled')
