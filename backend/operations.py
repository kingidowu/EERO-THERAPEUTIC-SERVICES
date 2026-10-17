"""Assigned tasks and staff-managed waitlist offers for the fictional workspace."""
from datetime import date,datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from planning import aware

PRIORITIES=('High','Normal','Low')

class OperationsMixin:
    def _page(self,limit,offset):
        if type(limit) is not int or not 1<=limit<=200 or type(offset) is not int or offset<0:
            raise ValueError('Invalid pagination')

    def _task_assignee(self,p,case_id,user_id):
        from core import Denied
        row=self.db.execute("SELECT 1 FROM staff s JOIN assignments a ON a.org_id=s.org_id AND a.user_id=s.user_id WHERE s.org_id=? AND s.user_id=? AND s.active=1 AND s.role IN ('administrator','supervisor','clinician','intake') AND a.case_id=?",(p.org_id,user_id,case_id)).fetchone()
        if not row:raise Denied('Choose active staff assigned to this case')

    def save_work_task(self,p,case_id,title,due_date,assigned_user_id,priority='Normal',*,task_id=None,expected_version=None):
        from core import Denied,identifier,utcnow
        if not isinstance(case_id,str) or not case_id:raise ValueError('Choose a case folder')
        if not isinstance(assigned_user_id,str) or not assigned_user_id:raise ValueError('Choose assigned staff')
        if not isinstance(title,str) or not title.strip() or len(title)>150:raise ValueError('Task title must have 1–150 characters')
        if not isinstance(due_date,str):raise ValueError('A due date is required')
        date.fromisoformat(due_date)
        if priority not in PRIORITIES:raise ValueError('Invalid task priority')
        tid=task_id or identifier();now=utcnow()
        with self.db:
            self.db.execute('BEGIN IMMEDIATE');self._allowed(p,'task',case_id);self._task_assignee(p,case_id,assigned_user_id)
            row=self.db.execute('SELECT t.*,COALESCE(d.version,0) AS version FROM tasks t LEFT JOIN task_details d ON d.task_id=t.id WHERE t.org_id=? AND t.id=?',(p.org_id,tid)).fetchone()
            if task_id:
                if not row:raise Denied('Task unavailable')
                self._allowed(p,'task',row['case_id'])
                if type(expected_version) is not int or row['version']!=expected_version:raise ValueError('Task changed; refresh before saving')
            if (not row or row['completed_at'] is None) and self.db.execute('SELECT status FROM cases WHERE org_id=? AND id=?',(p.org_id,case_id)).fetchone()['status']=='closed':raise ValueError('Reopen the case before adding open tasks')
            title_bytes=self.vault.seal(title.strip().encode(),f'{p.org_id}/{tid}/task')
            if row:self.db.execute('UPDATE tasks SET case_id=?,encrypted_title=?,due_date=? WHERE org_id=? AND id=?',(case_id,title_bytes,due_date,p.org_id,tid))
            else:self.db.execute('INSERT INTO tasks(id,org_id,case_id,encrypted_title,due_date,created_at) VALUES(?,?,?,?,?,?)',(tid,p.org_id,case_id,title_bytes,due_date,now))
            version=row['version']+1 if row else 1
            self.db.execute('INSERT INTO task_details VALUES(?,?,?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET assigned_user_id=excluded.assigned_user_id,priority=excluded.priority,version=excluded.version,updated_at=excluded.updated_at',(tid,p.org_id,assigned_user_id,priority,version,now))
            self._audit(p,'task.update' if row else 'task.create',tid)
        return {'id':tid,'version':version}

    def set_work_task_state(self,p,task_id,expected_version,status):
        from core import Denied,utcnow
        if status not in ('Open','Done'):raise ValueError('Invalid task state')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row=self.db.execute('SELECT t.*,COALESCE(d.version,0) AS version FROM tasks t LEFT JOIN task_details d ON d.task_id=t.id WHERE t.org_id=? AND t.id=?',(p.org_id,task_id)).fetchone()
            if not row:raise Denied('Task unavailable')
            self._allowed(p,'task',row['case_id'])
            if type(expected_version) is not int or row['version']!=expected_version:raise ValueError('Task changed; refresh before updating')
            if status=='Open' and self.db.execute('SELECT status FROM cases WHERE org_id=? AND id=?',(p.org_id,row['case_id'])).fetchone()['status']=='closed':raise ValueError('Reopen the case before reopening tasks')
            if row['version']==0:raise ValueError('Assign this legacy task before updating it')
            self.db.execute('UPDATE tasks SET completed_at=? WHERE org_id=? AND id=?',(utcnow() if status=='Done' else None,p.org_id,task_id))
            self.db.execute('UPDATE task_details SET version=version+1,updated_at=? WHERE task_id=?',(utcnow(),task_id))
            self._audit(p,'task.complete' if status=='Done' else 'task.reopen',task_id)
        return {'version':row['version']+1}

    def list_work_tasks(self,p,*,status='Open',assignee=None,priority=None,limit=100,offset=0):
        self._allowed(p,'task');role=self._role(p);self._page(limit,offset)
        if status not in ('Open','Done','Overdue','All') or (priority and priority not in PRIORITIES):raise ValueError('Invalid task filter')
        day=datetime.now(timezone.utc).astimezone(ZoneInfo(self.organization_timezone(p))).date().isoformat()
        rows=self.db.execute('''SELECT t.*,d.assigned_user_id,COALESCE(d.priority,'Normal') AS priority,COALESCE(d.version,0) AS version
         FROM tasks t LEFT JOIN task_details d ON d.task_id=t.id WHERE t.org_id=?
         AND (?='administrator' OR EXISTS(SELECT 1 FROM assignments a WHERE a.org_id=t.org_id AND a.case_id=t.case_id AND a.user_id=?))
         AND (?='All' OR (?='Done' AND t.completed_at IS NOT NULL) OR (?='Open' AND t.completed_at IS NULL) OR (?='Overdue' AND t.completed_at IS NULL AND t.due_date<?))
         AND (? IS NULL OR d.assigned_user_id=?) AND (? IS NULL OR COALESCE(d.priority,'Normal')=?)
         ORDER BY t.due_date,CASE COALESCE(d.priority,'Normal') WHEN 'High' THEN 0 WHEN 'Normal' THEN 1 ELSE 2 END,t.created_at,t.id LIMIT ? OFFSET ?''',(p.org_id,role,p.user_id,status,status,status,status,day,assignee,assignee,priority,priority,limit,offset)).fetchall()
        result=[]
        for row in rows:
            item={k:row[k] for k in ('id','case_id','due_date','completed_at','assigned_user_id','priority','version')}
            item.update(title=self.vault.open(row['encrypted_title'],f"{p.org_id}/{row['id']}/task").decode(),overdue=row['completed_at'] is None and row['due_date']<day)
            result.append(item)
        with self.db:self._audit(p,'tasks.read','tasks')
        return result

    def add_waitlist(self,p,case_id,service,not_before,priority='Normal'):
        from core import identifier,utcnow
        if not isinstance(case_id,str) or not case_id:raise ValueError('Choose a case folder')
        if not isinstance(service,str) or not service.strip() or len(service)>80:raise ValueError('Service preference must have 1–80 characters')
        if not isinstance(not_before,str):raise ValueError('An earliest date is required')
        date.fromisoformat(not_before)
        if priority not in PRIORITIES:raise ValueError('Invalid queue priority')
        wid=identifier();now=utcnow()
        with self.db:
            self.db.execute('BEGIN IMMEDIATE');self._allowed(p,'waitlist',case_id)
            if self.db.execute('SELECT status FROM cases WHERE org_id=? AND id=?',(p.org_id,case_id)).fetchone()['status']=='closed':raise ValueError('Reopen the case before creating a waitlist request')
            if self.db.execute("SELECT 1 FROM waitlist WHERE org_id=? AND case_id=? AND status IN ('Waiting','Offered')",(p.org_id,case_id)).fetchone():raise ValueError('This case already has an active waitlist entry')
            self.db.execute('INSERT INTO waitlist(id,org_id,case_id,encrypted_service,not_before,priority,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',(wid,p.org_id,case_id,self.vault.seal(service.strip().encode(),f'{p.org_id}/{wid}/service'),not_before,priority,now,now))
            self._audit(p,'waitlist.create',wid)
        return {'id':wid,'version':1}

    def _waitlist_row(self,p,wid,expected_version=None):
        from core import Denied
        row=self.db.execute('SELECT * FROM waitlist WHERE org_id=? AND id=?',(p.org_id,wid)).fetchone()
        if not row:raise Denied('Waitlist entry unavailable')
        self._allowed(p,'waitlist',row['case_id'])
        if expected_version is not None and (type(expected_version) is not int or row['version']!=expected_version):raise ValueError('Waitlist entry changed; refresh before updating')
        return row

    def offer_waitlist(self,p,wid,expected_version,clinician_id,title,starts_at,duration,location):
        from core import utcnow
        if type(expected_version) is not int:raise ValueError('A version is required')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE');row=self._waitlist_row(p,wid,expected_version)
            if row['status']!='Waiting':raise ValueError('Return the entry to Waiting before recording a new offer')
            title,start,end=self._schedule_values(p,row['case_id'],clinician_id,title,starts_at,duration,location,'Scheduled')
            now=datetime.now(timezone.utc)
            if aware(start)<=now:raise ValueError('Choose a future session time')
            if aware(start).astimezone(ZoneInfo(self.organization_timezone(p))).date().isoformat()<row['not_before']:raise ValueError('The slot is before the earliest requested date')
            self._check_availability(p,clinician_id,start,end);self._schedule_conflict(p,row['case_id'],clinician_id,start,end)
            expiry=min(now+timedelta(hours=48),aware(start)).isoformat()
            self.db.execute("UPDATE waitlist SET status='Offered',clinician_id=?,encrypted_offer_title=?,starts_at=?,ends_at=?,location=?,expires_at=?,version=version+1,updated_at=? WHERE id=?",(clinician_id,self.vault.seal(title.encode(),f'{p.org_id}/{wid}/offer'),start,end,location,expiry,utcnow(),wid))
            self._audit(p,'waitlist.offer',wid)
        return {'version':row['version']+1,'expires_at':expiry}

    def resolve_waitlist(self,p,wid,expected_version,action):
        from core import utcnow
        if type(expected_version) is not int or action not in ('Declined','Withdrawn'):raise ValueError('A version and valid queue action are required')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE');row=self._waitlist_row(p,wid,expected_version)
            if row['status'] in ('Booked','Withdrawn'):raise ValueError('This waitlist entry is closed')
            if action=='Declined' and row['status']!='Offered':raise ValueError('An offer is required to return to Waiting')
            self.db.execute('UPDATE waitlist SET status=?,clinician_id=NULL,encrypted_offer_title=NULL,starts_at=NULL,ends_at=NULL,location=NULL,expires_at=NULL,version=version+1,updated_at=? WHERE id=?',('Waiting' if action=='Declined' else 'Withdrawn',utcnow(),wid))
            self._audit(p,'waitlist.decline' if action=='Declined' else 'waitlist.withdraw',wid)
        return {'version':row['version']+1}

    def book_waitlist(self,p,wid,expected_version,confirmation):
        from core import utcnow
        if confirmation!='confirmed' or type(expected_version) is not int:raise ValueError('Confirm family acceptance and include the current version')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE');row=self._waitlist_row(p,wid)
            if row['status']=='Booked':return {'id':row['appointment_id'],'replayed':True}
            if row['version']!=expected_version:raise ValueError('Waitlist entry changed; refresh before booking')
            if row['status']!='Offered':raise ValueError('A recorded offer is required')
            if aware(row['expires_at'])<=datetime.now(timezone.utc):raise ValueError('This offer expired; return it to Waiting and choose another slot')
            title=self.vault.open(row['encrypted_offer_title'],f'{p.org_id}/{wid}/offer').decode()
            duration=int((aware(row['ends_at'])-aware(row['starts_at'])).total_seconds()/60)
            result=self._write_appointment(p,row['case_id'],row['clinician_id'],title,row['starts_at'],duration,row['location'],'Scheduled')
            self.db.execute("UPDATE waitlist SET status='Booked',appointment_id=?,version=version+1,updated_at=? WHERE id=?",(result['id'],utcnow(),wid));self._audit(p,'waitlist.book',wid)
        return {'id':result['id'],'replayed':False}

    def list_waitlist(self,p,*,status='Active',limit=100,offset=0):
        self._allowed(p,'read_case');role=self._role(p);self._page(limit,offset)
        if status not in ('Active','Waiting','Offered','Booked','Withdrawn','All'):raise ValueError('Invalid waitlist filter')
        rows=self.db.execute('''SELECT * FROM waitlist w WHERE org_id=?
         AND (?='administrator' OR EXISTS(SELECT 1 FROM assignments a WHERE a.org_id=w.org_id AND a.case_id=w.case_id AND a.user_id=?))
         AND (?='All' OR (?='Active' AND w.status IN ('Waiting','Offered')) OR w.status=?)
         ORDER BY CASE priority WHEN 'High' THEN 0 WHEN 'Normal' THEN 1 ELSE 2 END,created_at,id LIMIT ? OFFSET ?''',(p.org_id,role,p.user_id,status,status,status,limit,offset)).fetchall()
        result=[];now=datetime.now(timezone.utc)
        for row in rows:
            item={k:row[k] for k in ('id','case_id','not_before','priority','status','version','created_at','clinician_id','starts_at','ends_at','location','expires_at','appointment_id')}
            item.update(service=self.vault.open(row['encrypted_service'],f"{p.org_id}/{row['id']}/service").decode(),offer_title=self.vault.open(row['encrypted_offer_title'],f"{p.org_id}/{row['id']}/offer").decode() if row['encrypted_offer_title'] else None,expired=row['status']=='Offered' and aware(row['expires_at'])<=now)
            result.append(item)
        with self.db:self._audit(p,'waitlist.read','waitlist')
        return result
