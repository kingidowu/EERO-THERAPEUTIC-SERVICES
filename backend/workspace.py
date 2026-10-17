"""Case administration for the authenticated fictional-data workspace."""
class WorkspaceMixin:
    def create_workspace_case(self,p,label):
        from core import identifier,utcnow
        if not isinstance(label,str) or not label.strip() or len(label)>120:raise ValueError('Case label must have 1–120 characters')
        cid=identifier()
        with self.db:
            self.db.execute('BEGIN IMMEDIATE');self._allowed(p,'create_case')
            self.db.execute('INSERT INTO cases(id,org_id,encrypted_label,created_at) VALUES(?,?,?,?)',(cid,p.org_id,self.vault.seal(label.strip().encode(),f'{p.org_id}/{cid}/label'),utcnow()))
            self.db.execute('INSERT INTO assignments VALUES(?,?,?)',(p.org_id,cid,p.user_id))
            self.db.execute('INSERT INTO case_versions VALUES(?,?,?)',(cid,1,utcnow()));self._audit(p,'case.create',cid)
        return {'id':cid,'version':1}

    def _workspace_case(self,p,cid,version):
        from core import Denied
        self._allowed(p,'read_case',cid)
        row=self.db.execute('SELECT c.*,COALESCE(v.version,0) AS version FROM cases c LEFT JOIN case_versions v ON v.case_id=c.id WHERE c.org_id=? AND c.id=?',(p.org_id,cid)).fetchone()
        if not row:raise Denied('Case unavailable')
        if type(version) is not int or row['version']!=version:raise ValueError('Case changed; refresh before saving')
        return row

    def _bump_case(self,cid,version):
        from core import utcnow
        self.db.execute('INSERT INTO case_versions VALUES(?,?,?) ON CONFLICT(case_id) DO UPDATE SET version=excluded.version,updated_at=excluded.updated_at',(cid,version+1,utcnow()))

    def update_workspace_case(self,p,cid,version,label,status):
        from core import utcnow
        if not isinstance(label,str) or not label.strip() or len(label)>120 or status not in ('active','closed'):raise ValueError('Use a valid case label and status')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE');self._allowed(p,'create_case');row=self._workspace_case(p,cid,version)
            if status=='closed':
                if self.db.execute("SELECT 1 FROM appointments WHERE org_id=? AND case_id=? AND status='Scheduled' AND ends_at>?",(p.org_id,cid,utcnow())).fetchone():raise ValueError('Cancel or complete future sessions before closing the case')
                if self.db.execute("SELECT 1 FROM waitlist WHERE org_id=? AND case_id=? AND status IN ('Waiting','Offered')",(p.org_id,cid)).fetchone():raise ValueError('Resolve the active waitlist request before closing the case')
                if self.db.execute('SELECT 1 FROM tasks WHERE org_id=? AND case_id=? AND completed_at IS NULL',(p.org_id,cid)).fetchone():raise ValueError('Complete open follow-up tasks before closing the case')
            self.db.execute('UPDATE cases SET encrypted_label=?,status=? WHERE org_id=? AND id=?',(self.vault.seal(label.strip().encode(),f'{p.org_id}/{cid}/label'),status,p.org_id,cid));self._bump_case(cid,row['version']);self._audit(p,'case.update',cid)
        return {'version':row['version']+1}

    def update_case_assignment(self,p,cid,version,user_id,action):
        from core import Denied,utcnow
        if action not in ('Assign','Remove') or not isinstance(user_id,str) or not user_id:raise ValueError('Choose staff and an assignment action')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE');self._allowed(p,'assign',cid);row=self._workspace_case(p,cid,version)
            staff=self.db.execute('SELECT role,active FROM staff WHERE org_id=? AND user_id=?',(p.org_id,user_id)).fetchone()
            if not staff or staff['role']=='billing' or (action=='Assign' and not staff['active']):raise Denied('Choose active organization care staff')
            if action=='Assign':self.db.execute('INSERT OR IGNORE INTO assignments VALUES(?,?,?)',(p.org_id,cid,user_id))
            else:
                if self.db.execute("SELECT 1 FROM appointments WHERE org_id=? AND case_id=? AND clinician_id=? AND status='Scheduled' AND ends_at>?",(p.org_id,cid,user_id,utcnow())).fetchone():raise ValueError('Reassign or cancel future sessions before removing this clinician')
                if self.db.execute('SELECT 1 FROM tasks t JOIN task_details d ON d.task_id=t.id WHERE t.org_id=? AND t.case_id=? AND d.assigned_user_id=? AND t.completed_at IS NULL',(p.org_id,cid,user_id)).fetchone():raise ValueError('Reassign or complete open tasks before removing this staff member')
                self.db.execute('DELETE FROM assignments WHERE org_id=? AND case_id=? AND user_id=?',(p.org_id,cid,user_id))
            self._bump_case(cid,row['version']);self._audit(p,'case.assign' if action=='Assign' else 'case.unassign',cid)
        return {'version':row['version']+1}
