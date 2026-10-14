import sqlite3
import unittest
from cryptography.exceptions import InvalidTag
from core import Backend, Principal, Vault, Denied, NotReady

class Controls(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.backend=Backend(self.db,b'k'*32)
        with self.db:
            self.db.executemany('INSERT INTO organizations VALUES(?,?)',[('eero','Eero sample'),('other','Other sample')])
            self.db.executemany('INSERT INTO staff(org_id,user_id,role) VALUES(?,?,?)',[
                ('eero','admin','administrator'),('eero','reviewer','supervisor'),
                ('eero','clinician','clinician'),('eero','second','clinician'),
                ('eero','intake','intake'),('eero','billing','billing'),('other','other-admin','administrator')])
        self.admin=Principal('eero','admin');self.reviewer=Principal('eero','reviewer');self.clinician=Principal('eero','clinician');self.intake=Principal('eero','intake')
        self.cid=self.backend.create_case(self.admin,'Fictional case')
        for uid in ['reviewer','clinician','intake']: self.backend.assign(self.admin,self.cid,uid)
    def tearDown(self): self.db.close()
    def upload(self,p=None): return self.backend.upload(p or self.intake,self.cid,'Blank sample',b'%PDF-1.7 fictional','application/pdf')
    def clean(self,did): self.backend.record_scan(self.admin,did,clean=True,scanner_reference='fixture-result')
    def test_cross_organization_read_is_denied(self):
        with self.assertRaises(Denied): self.backend.read_case(Principal('other','other-admin'),self.cid)
    def test_case_assignment_required(self):
        with self.assertRaises(Denied): self.backend.read_case(Principal('eero','second'),self.cid)
    def test_inactive_membership_revokes_access(self):
        self.db.execute('UPDATE staff SET active=0 WHERE user_id=?',('clinician',));self.db.commit()
        with self.assertRaises(Denied): self.backend.read_case(self.clinician,self.cid)
    def test_billing_cannot_read_case_content(self):
        with self.assertRaises(Denied): self.backend.read_case(Principal('eero','billing'),self.cid)
    def test_physical_database_does_not_store_sensitive_field_plaintext(self):
        self.backend.add_note(self.clinician,self.cid,'Fictional sensitive text')
        dump='\n'.join(self.db.iterdump())
        self.assertNotIn('Fictional sensitive text',dump);self.assertNotIn('Fictional case',dump)
    def test_ciphertext_tamper_and_context_swap_fail(self):
        vault=Vault(b'k'*32);sealed=vault.seal(b'sample','eero/case')
        with self.assertRaises(InvalidTag): vault.open(sealed,'other/case')
        with self.assertRaises(InvalidTag): vault.open(sealed[:-1]+bytes([sealed[-1]^1]),'eero/case')
    def test_quarantined_document_cannot_be_read_or_approved(self):
        did=self.upload()
        with self.assertRaises(NotReady): self.backend.read_document(self.clinician,did)
        with self.assertRaises(NotReady): self.backend.approve(self.reviewer,did)
    def test_scan_role_is_restricted(self):
        with self.assertRaises(Denied): self.backend.record_scan(self.intake,self.upload(),clean=True,scanner_reference='fake')
    def test_clean_file_and_separate_review(self):
        did=self.upload();self.clean(did);self.backend.approve(self.reviewer,did)
        self.assertEqual(self.backend.read_document(self.clinician,did),b'%PDF-1.7 fictional')
    def test_self_approval_is_denied(self):
        did=self.upload(self.reviewer);self.clean(did)
        with self.assertRaises(Denied): self.backend.approve(self.reviewer,did)
    def test_rejected_file_cannot_be_read(self):
        did=self.upload();self.backend.record_scan(self.admin,did,clean=False,scanner_reference='fixture-reject')
        with self.assertRaises(NotReady): self.backend.read_document(self.clinician,did)
    def test_invalid_media_rejected(self):
        with self.assertRaises(ValueError): self.backend.upload(self.intake,self.cid,'fake',b'<script>x</script>','application/pdf')
    def test_psychotherapy_is_author_only(self):
        nid=self.backend.add_note(self.clinician,self.cid,'Fictional private note','psychotherapy')
        self.assertEqual(self.backend.read_note(self.clinician,nid),'Fictional private note')
        with self.assertRaises(Denied): self.backend.read_note(self.reviewer,nid)
        with self.assertRaises(Denied): self.backend.read_note(self.admin,nid)
    def test_intake_cannot_read_progress_note(self):
        nid=self.backend.add_note(self.clinician,self.cid,'Sample progress')
        with self.assertRaises(Denied): self.backend.read_note(self.intake,nid)
    def test_audit_read_recorded_and_update_delete_rejected(self):
        self.backend.read_case(self.clinician,self.cid)
        self.assertEqual(self.db.execute('SELECT action FROM audit_events ORDER BY sequence DESC LIMIT 1').fetchone()[0],'case.read')
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute('DELETE FROM audit_events')
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute("UPDATE audit_events SET action='changed'")
    def test_expired_authorization_requires_approved_evidence(self):
        did=self.upload()
        with self.assertRaises(NotReady): self.backend.record_authorization(self.intake,self.cid,'service',did,'2026-10-01')
        self.clean(did);self.backend.approve(self.reviewer,did)
        aid=self.backend.record_authorization(self.intake,self.cid,'service',did,'2026-10-01')
        self.assertEqual(self.backend.brain(self.clinician,self.cid,'2026-10-10')['expired_authorizations'],1)
        self.backend.revoke_authorization(self.intake,aid)
        self.assertEqual(self.backend.brain(self.clinician,self.cid,'2026-10-10')['expired_authorizations'],0)
    def test_task_completion_updates_operational_summary(self):
        tid=self.backend.create_task(self.intake,self.cid,'Check sample form','2026-10-01')
        self.assertEqual(self.backend.brain(self.clinician,self.cid,'2026-10-10')['overdue_tasks'],1)
        self.backend.complete_task(self.clinician,tid)
        result=self.backend.brain(self.clinician,self.cid,'2026-10-10')
        self.assertEqual(result['overdue_tasks'],0);self.assertFalse(result['clinical_decisions_enabled'])
    def test_real_patient_mode_locked(self):
        with self.assertRaises(NotReady): Backend(self.db,b'k'*32,real_patient_data=True)

if __name__=='__main__': unittest.main()
