"""Eero backend service foundation. No public server; authenticated adapter still required."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone, date
from pathlib import Path
import hashlib
import json
import sqlite3
import uuid
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from scheduling import SchedulingMixin

class Denied(PermissionError): pass
class NotReady(RuntimeError): pass

@dataclass(frozen=True)
class Principal:
    # Construct ONLY after identity-provider validation; never from a request body/header directly.
    org_id: str
    user_id: str

def utcnow(): return datetime.now(timezone.utc).isoformat()
def identifier(): return str(uuid.uuid4())

class Vault:
    """Development AES-GCM encryption with tenant/resource-bound authenticated data.
    Production adapter must use envelope encryption and managed KMS with rotation.
    """
    def __init__(self, key: bytes):
        if len(key) != 32: raise ValueError('Use a 32-byte encryption key')
        self.cipher = AESGCM(key)
    def seal(self, value: bytes, context: str) -> bytes:
        import os
        nonce = os.urandom(12)
        return nonce + self.cipher.encrypt(nonce, value, context.encode())
    def open(self, value: bytes, context: str) -> bytes:
        return self.cipher.decrypt(value[:12], value[12:], context.encode())

class Backend(SchedulingMixin):
    """Local validation adapter. PHI ingestion is deliberately unavailable.
    Role and case assignment checks are server-side and read from the database.
    """
    def __init__(self, connection: sqlite3.Connection, key: bytes, *, real_patient_data=False):
        if real_patient_data:
            raise NotReady('Production provider agreements, identity integration and validation are not configured')
        self.db = connection
        self.db.row_factory = sqlite3.Row
        self.vault = Vault(key)
        self.db.executescript(Path(__file__).with_name('schema.sql').read_text())

    def _role(self, p: Principal):
        row = self.db.execute('SELECT role FROM staff WHERE org_id=? AND user_id=? AND active=1', (p.org_id,p.user_id)).fetchone()
        if not row: raise Denied('Active staff membership required')
        return row['role']

    def _allowed(self, p, action, case_id=None):
        role = self._role(p)
        permitted = {
            'create_case': {'administrator','supervisor','intake'},
            'schedule': {'administrator','supervisor','clinician','intake'},
            'assign': {'administrator','supervisor'},
            'read_case': {'administrator','supervisor','clinician','intake'},
            'upload': {'administrator','supervisor','clinician','intake'},
            'scan': {'administrator'},
            'approve': {'supervisor'},
            'note': {'clinician'},
            'read_note': {'supervisor','clinician'},
            'task': {'administrator','supervisor','clinician','intake'},
            'authorization': {'supervisor','intake'},
        }
        if role not in permitted.get(action,set()): raise Denied('Permission denied')
        if case_id:
            case = self.db.execute('SELECT 1 FROM cases WHERE org_id=? AND id=?',(p.org_id,case_id)).fetchone()
            if not case: raise Denied('Case unavailable')
            if role != 'administrator':
                assigned = self.db.execute('SELECT 1 FROM assignments WHERE org_id=? AND case_id=? AND user_id=?',(p.org_id,case_id,p.user_id)).fetchone()
                if not assigned: raise Denied('Case assignment required')

    def _audit(self,p,action,resource):
        previous = self.db.execute('SELECT event_hash FROM audit_events WHERE org_id=? ORDER BY sequence DESC LIMIT 1',(p.org_id,)).fetchone()
        previous_hash = previous[0] if previous else '0'*64
        timestamp = utcnow()
        data = json.dumps([p.org_id,p.user_id,action,resource,timestamp,previous_hash],separators=(',',':'))
        digest = hashlib.sha256(data.encode()).hexdigest()
        self.db.execute('INSERT INTO audit_events(org_id,user_id,action,resource_id,occurred_at,previous_hash,event_hash) VALUES(?,?,?,?,?,?,?)',(p.org_id,p.user_id,action,resource,timestamp,previous_hash,digest))

    def create_case(self,p,label):
        self._allowed(p,'create_case')
        if not label.strip() or len(label)>120: raise ValueError('Case label required, maximum 120 characters')
        cid = identifier()
        with self.db:
            self.db.execute('INSERT INTO cases(id,org_id,encrypted_label,created_at) VALUES(?,?,?,?)',(cid,p.org_id,self.vault.seal(label.encode(),f'{p.org_id}/{cid}/label'),utcnow()))
            self.db.execute('INSERT INTO assignments VALUES(?,?,?)',(p.org_id,cid,p.user_id))
            self._audit(p,'case.create',cid)
        return cid

    def assign(self,p,case_id,user_id):
        self._allowed(p,'assign',case_id)
        if not self.db.execute('SELECT 1 FROM staff WHERE org_id=? AND user_id=? AND active=1',(p.org_id,user_id)).fetchone(): raise Denied('Active organization staff required')
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO assignments VALUES(?,?,?)',(p.org_id,case_id,user_id))
            self._audit(p,'case.assign',case_id)

    def read_case(self,p,case_id):
        self._allowed(p,'read_case',case_id)
        with self.db:
            row = self.db.execute('SELECT * FROM cases WHERE org_id=? AND id=?',(p.org_id,case_id)).fetchone()
            label = self.vault.open(row['encrypted_label'],f'{p.org_id}/{case_id}/label').decode()
            self._audit(p,'case.read',case_id)
        return {'id':case_id,'label':label,'status':row['status']}

    def upload(self,p,case_id,title,content,media_type):
        self._allowed(p,'upload',case_id)
        if not title.strip() or len(title)>150: raise ValueError('Document title required, maximum 150 characters')
        if not 0<len(content)<=15*1024*1024: raise ValueError('File must be between 1 byte and 15 MB')
        signatures = {'application/pdf':b'%PDF-', 'image/png':b'\x89PNG\r\n\x1a\n','image/jpeg':b'\xff\xd8\xff'}
        if media_type not in signatures or not content.startswith(signatures[media_type]): raise ValueError('File type or signature invalid')
        did = identifier()
        with self.db:
            self.db.execute('INSERT INTO documents(id,org_id,case_id,encrypted_title,encrypted_content,digest,media_type,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(did,p.org_id,case_id,self.vault.seal(title.encode(),f'{p.org_id}/{did}/title'),self.vault.seal(content,f'{p.org_id}/{did}/file'),hashlib.sha256(content).hexdigest(),media_type,p.user_id,utcnow()))
            self._audit(p,'document.upload.quarantined',did)
        return did

    def record_scan(self,p,document_id,*,clean,scanner_reference):
        """Trusted scanner callback only. No HTTP route exists; production needs service identity verification."""
        d = self._doc(p,document_id,'scan')
        if not scanner_reference or len(scanner_reference)>120: raise ValueError('Scanner result reference required')
        if d['scan_state'] != 'quarantined': raise ValueError('A quarantined file is required')
        with self.db:
            self.db.execute('UPDATE documents SET scan_state=? WHERE org_id=? AND id=?',('clean' if clean else 'rejected',p.org_id,document_id))
            self._audit(p,'document.scan.clean' if clean else 'document.scan.rejected',document_id)

    def _doc(self,p,did,action):
        d=self.db.execute('SELECT * FROM documents WHERE org_id=? AND id=?',(p.org_id,did)).fetchone()
        if not d: raise Denied('Document unavailable')
        self._allowed(p,action,d['case_id'])
        return d

    def read_document(self,p,did):
        d=self._doc(p,did,'read_case')
        if d['scan_state']!='clean': raise NotReady('Document is quarantined or rejected')
        content=self.vault.open(d['encrypted_content'],f'{p.org_id}/{did}/file')
        if hashlib.sha256(content).hexdigest()!=d['digest']: raise NotReady('Integrity check failed')
        with self.db: self._audit(p,'document.read',did)
        return content

    def approve(self,p,did):
        d=self._doc(p,did,'approve')
        if d['scan_state']!='clean': raise NotReady('A clean scanner result is required')
        if d['created_by']==p.user_id: raise Denied('A separate reviewer is required')
        if d['review_state']=='approved': raise ValueError('Document already approved')
        with self.db:
            self.db.execute('UPDATE documents SET review_state=?,reviewed_by=? WHERE org_id=? AND id=?',('approved',p.user_id,p.org_id,did))
            self._audit(p,'document.approve',did)

    def add_note(self,p,case_id,body,kind='progress'):
        self._allowed(p,'note',case_id)
        if kind not in ('progress','psychotherapy'): raise ValueError('Invalid note kind')
        if not body.strip() or len(body)>100000: raise ValueError('Note must have 1–100000 characters')
        nid=identifier()
        with self.db:
            self.db.execute('INSERT INTO notes VALUES(?,?,?,?,?,?,?)',(nid,p.org_id,case_id,p.user_id,kind,self.vault.seal(body.encode(),f'{p.org_id}/{nid}/note'),utcnow()))
            self._audit(p,'note.create.'+kind,nid)
        return nid

    def read_note(self,p,nid):
        n=self.db.execute('SELECT * FROM notes WHERE org_id=? AND id=?',(p.org_id,nid)).fetchone()
        if not n: raise Denied('Note unavailable')
        self._allowed(p,'read_note',n['case_id'])
        # Deliberately narrower than all legally permitted exceptions: no disclosure implementation.
        if n['kind']=='psychotherapy' and n['author_id']!=p.user_id: raise Denied('Separate psychotherapy notes are restricted to their author in this foundation')
        value=self.vault.open(n['encrypted_body'],f'{p.org_id}/{nid}/note').decode()
        with self.db: self._audit(p,'note.read.'+n['kind'],nid)
        return value

    def create_task(self,p,case_id,title,due):
        self._allowed(p,'task',case_id)
        date.fromisoformat(due)
        if not title.strip() or len(title)>150: raise ValueError('Task title required, maximum 150 characters')
        tid=identifier()
        with self.db:
            self.db.execute('INSERT INTO tasks(id,org_id,case_id,encrypted_title,due_date,created_at) VALUES(?,?,?,?,?,?)',(tid,p.org_id,case_id,self.vault.seal(title.encode(),f'{p.org_id}/{tid}/task'),due,utcnow()))
            self._audit(p,'task.create',tid)
        return tid

    def complete_task(self,p,tid):
        row=self.db.execute('SELECT * FROM tasks WHERE org_id=? AND id=?',(p.org_id,tid)).fetchone()
        if not row: raise Denied('Task unavailable')
        self._allowed(p,'task',row['case_id'])
        with self.db:
            self.db.execute('UPDATE tasks SET completed_at=? WHERE org_id=? AND id=?',(utcnow(),p.org_id,tid))
            self._audit(p,'task.complete',tid)

    def record_authorization(self,p,case_id,kind,evidence_document_id,expires_on):
        self._allowed(p,'authorization',case_id)
        if kind not in ('service','disclosure','psychotherapy_disclosure'): raise ValueError('Invalid authorization kind')
        date.fromisoformat(expires_on)
        d=self._doc(p,evidence_document_id,'read_case')
        if d['case_id']!=case_id or d['review_state']!='approved' or d['scan_state']!='clean': raise NotReady('An approved evidence document from this case is required')
        aid=identifier()
        with self.db:
            self.db.execute('INSERT INTO authorizations(id,org_id,case_id,kind,evidence_document_id,expires_on,created_at) VALUES(?,?,?,?,?,?,?)',(aid,p.org_id,case_id,kind,evidence_document_id,expires_on,utcnow()))
            self._audit(p,'authorization.record',aid)
        return aid

    def revoke_authorization(self,p,aid):
        a=self.db.execute('SELECT * FROM authorizations WHERE org_id=? AND id=?',(p.org_id,aid)).fetchone()
        if not a: raise Denied('Authorization unavailable')
        self._allowed(p,'authorization',a['case_id'])
        with self.db:
            self.db.execute('UPDATE authorizations SET revoked_at=? WHERE org_id=? AND id=?',(utcnow(),p.org_id,aid))
            self._audit(p,'authorization.revoke',aid)

    def brain(self,p,case_id,as_of=None):
        """Deterministic operational reminders. No diagnoses, medical decisions or automatic disclosure."""
        self._allowed(p,'read_case',case_id)
        day=as_of or date.today().isoformat();date.fromisoformat(day)
        pending=self.db.execute('SELECT COUNT(*) FROM documents WHERE org_id=? AND case_id=? AND review_state=?',(p.org_id,case_id,'needs_review')).fetchone()[0]
        overdue=self.db.execute('SELECT COUNT(*) FROM tasks WHERE org_id=? AND case_id=? AND due_date<? AND completed_at IS NULL',(p.org_id,case_id,day)).fetchone()[0]
        auth=self.db.execute('SELECT COUNT(*) FROM authorizations WHERE org_id=? AND case_id=? AND revoked_at IS NULL AND expires_on<?',(p.org_id,case_id,day)).fetchone()[0]
        with self.db: self._audit(p,'case.operational_summary',case_id)
        return {'documents_needing_review':pending,'overdue_tasks':overdue,'expired_authorizations':auth,'clinical_decisions_enabled':False}
