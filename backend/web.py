"""Same-origin staff scheduling API with provider-managed OIDC sign-in."""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from urllib.parse import urlparse
from flask import Flask, abort, g, jsonify, redirect, request, session, url_for
from authlib.integrations.flask_client import OAuth
from authlib.integrations.base_client.errors import OAuthError
from joserfc.errors import JoseError
from dotenv import load_dotenv
from core import Backend, Denied, NotReady, Principal
from planning import aware, local_start

ROOT=Path(__file__).resolve().parent.parent

def create_app(config=None):
    load_dotenv(ROOT/'.env',override=False)
    app=Flask(__name__,static_folder=str(ROOT/'dist'),static_url_path='')
    app.config.update(SECRET_KEY=os.environ.get('EERO_SESSION_SECRET'),DATABASE=os.environ.get('EERO_DATABASE',str(ROOT/'eero.db')),
        VAULT_KEY=os.environ.get('EERO_VAULT_KEY'),OIDC_ISSUER=os.environ.get('EERO_OIDC_ISSUER','https://accounts.google.com'),OIDC_METADATA_URL=os.environ.get('EERO_OIDC_METADATA_URL','https://accounts.google.com/.well-known/openid-configuration'),
        OIDC_CLIENT_ID=os.environ.get('EERO_OIDC_CLIENT_ID'),OIDC_CLIENT_SECRET=os.environ.get('EERO_OIDC_CLIENT_SECRET'),
        PUBLIC_URL=os.environ.get('EERO_PUBLIC_URL','http://127.0.0.1:8020'),SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',SESSION_COOKIE_SECURE=os.environ.get('EERO_LOCAL_HTTP')!='1',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),MAX_CONTENT_LENGTH=32768,TRUSTED_HOSTS=['localhost','127.0.0.1'])
    if config: app.config.update(config)
    if not app.config['SECRET_KEY'] or len(app.config['SECRET_KEY'])<32: raise RuntimeError('Configure a session secret of at least 32 characters')
    host=urlparse(app.config['PUBLIC_URL']).hostname
    if not host:raise RuntimeError('Configure a valid public origin')
    if host not in ('localhost','127.0.0.1') and not app.config['PUBLIC_URL'].startswith('https://'):raise RuntimeError('Remote origins require HTTPS')
    if not config or 'TRUSTED_HOSTS' not in config:app.config['TRUSTED_HOSTS']=[host]
    key=app.config['VAULT_KEY']
    if isinstance(key,str):key=bytes.fromhex(key)
    if not isinstance(key,bytes) or len(key)!=32:raise RuntimeError('Configure a 32-byte vault key')
    configured=all(app.config[k] for k in ('OIDC_ISSUER','OIDC_METADATA_URL','OIDC_CLIENT_ID','OIDC_CLIENT_SECRET'))
    if configured and any(not app.config[k].startswith('https://') for k in ('OIDC_ISSUER','OIDC_METADATA_URL')):raise RuntimeError('OIDC provider URLs must use HTTPS')
    if not app.config['TESTING'] and not app.config['SESSION_COOKIE_SECURE'] and urlparse(app.config['PUBLIC_URL']).hostname not in ('127.0.0.1','localhost'):raise RuntimeError('Remote sessions require secure cookies')
    oauth=OAuth(app)
    if configured:
        oauth.register('staff',server_metadata_url=app.config['OIDC_METADATA_URL'],client_id=app.config['OIDC_CLIENT_ID'],client_secret=app.config['OIDC_CLIENT_SECRET'],client_kwargs={'scope':'openid profile email','code_challenge_method':'S256','timeout':10})
    app.extensions['eero_oauth']=oauth

    def backend():
        if 'backend' not in g:
            g.db=sqlite3.connect(app.config['DATABASE'],timeout=10)
            g.backend=Backend(g.db,key)
        return g.backend
    @app.teardown_appcontext
    def close_db(error):
        if 'db' in g:g.db.close()
    def principal():
        token=session.get('staff_session')
        if not token:abort(401)
        b=backend();row=b.db.execute('SELECT * FROM web_sessions WHERE token_hash=? AND expires_at>?',(hashlib.sha256(token.encode()).hexdigest(),datetime.now(timezone.utc).isoformat())).fetchone()
        if not row:session.clear();abort(401)
        p=Principal(row['org_id'],row['user_id']);b._role(p);return p
    @app.before_request
    def protect():
        if request.path.startswith('/api/'):
            g.principal=principal()
            if request.method not in ('GET','HEAD','OPTIONS'):
                csrf=session.get('csrf','');received=request.headers.get('X-CSRF-Token','')
                if not csrf or not hmac.compare_digest(csrf,received):abort(403)
                if request.headers.get('Origin') and request.headers['Origin']!=app.config['PUBLIC_URL'].rstrip('/'):abort(403)
    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options']='nosniff';response.headers['X-Frame-Options']='DENY';response.headers['Referrer-Policy']='same-origin'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.path.startswith(('/api/','/auth/')):response.headers['Cache-Control']='no-store'
        return response
    @app.errorhandler(Denied)
    def denied(error):return jsonify(error='Access denied'),403
    @app.errorhandler(ValueError)
    def invalid(error):return jsonify(error=str(error)),400
    @app.errorhandler(NotReady)
    def not_ready(error):return jsonify(error=str(error)),503
    @app.errorhandler(401)
    def unauthorized(error):return jsonify(error='Sign in to continue'),401
    @app.errorhandler(403)
    def forbidden(error):return jsonify(error='Access denied'),403
    @app.errorhandler(JoseError)
    @app.errorhandler(OAuthError)
    def oauth_error(error):return jsonify(error='Sign-in validation failed. Please start again.'),401
    @app.get('/')
    def index():return app.send_static_file('staff.html')
    @app.get('/auth/status')
    def auth_status():return jsonify(ready=configured)
    @app.get('/auth/login')
    def login():
        if not configured:return jsonify(error='Staff sign-in has not been configured'),503
        return oauth.staff.authorize_redirect(app.config['PUBLIC_URL'].rstrip('/')+'/auth/callback',nonce=secrets.token_urlsafe(32))
    @app.get('/auth/callback')
    def callback():
        if not configured:abort(401)
        token=oauth.staff.authorize_access_token();claims=token.get('userinfo')
        if not claims or claims.get('iss')!=app.config['OIDC_ISSUER'] or not claims.get('sub'):abort(401)
        b=backend();row=b.db.execute('SELECT org_id,user_id FROM staff_identities WHERE issuer=? AND subject=?',(claims['iss'],claims['sub'])).fetchone()
        if not row:abort(403)
        p=Principal(row['org_id'],row['user_id']);b._role(p)
        if session.get('staff_session'):
            with b.db:b.db.execute('DELETE FROM web_sessions WHERE token_hash=?',(hashlib.sha256(session['staff_session'].encode()).hexdigest(),))
        session.clear();opaque=secrets.token_urlsafe(48);session['staff_session']=opaque;session['csrf']=secrets.token_urlsafe(32);session.permanent=True
        with b.db:
            b.db.execute('INSERT INTO web_sessions VALUES(?,?,?,?)',(hashlib.sha256(opaque.encode()).hexdigest(),p.org_id,p.user_id,(datetime.now(timezone.utc)+timedelta(hours=8)).isoformat()));b._audit(p,'session.login',p.user_id)
        return redirect('/staff.html')
    @app.post('/api/logout')
    def logout():
        b=backend()
        with b.db:b.db.execute('DELETE FROM web_sessions WHERE token_hash=?',(hashlib.sha256(session['staff_session'].encode()).hexdigest(),));b._audit(g.principal,'session.logout',g.principal.user_id)
        session.clear();return jsonify(ok=True)
    @app.get('/api/bootstrap')
    def bootstrap():
        b=backend();p=g.principal;role=b._role(p)
        if role not in ('administrator','supervisor','clinician','intake'):raise Denied()
        rows=b.db.execute("SELECT c.* FROM cases c WHERE c.org_id=? AND (?='administrator' OR EXISTS(SELECT 1 FROM assignments a WHERE a.org_id=c.org_id AND a.case_id=c.id AND a.user_id=?)) ORDER BY created_at,c.id LIMIT 501",(p.org_id,role,p.user_id)).fetchall()
        if len(rows)>500:raise NotReady('Workspace exceeds the configured case limit')
        cases=[{'id':r['id'],'label':b.vault.open(r['encrypted_label'],f"{p.org_id}/{r['id']}/label").decode()} for r in rows]
        staff=b.db.execute("SELECT user_id FROM staff WHERE org_id=? AND role='clinician' AND active=1 AND (?='administrator' OR user_id=? OR EXISTS(SELECT 1 FROM assignments a JOIN assignments mine ON mine.org_id=a.org_id AND mine.case_id=a.case_id WHERE a.org_id=staff.org_id AND a.user_id=staff.user_id AND mine.user_id=?))",(p.org_id,role,p.user_id,p.user_id)).fetchall()
        clinicians=[{'id':r[0],'name':r[0]} for r in staff]
        ids={c['id'] for c in cases};allowed_staff={c['id'] for c in clinicians}
        assignments=[{'case_id':r['case_id'],'clinician_id':r['user_id']} for r in b.db.execute('SELECT case_id,user_id FROM assignments WHERE org_id=?',(p.org_id,)) if r['case_id'] in ids and r['user_id'] in allowed_staff]
        availability=[{'clinician_id':r['clinician_id'],'windows':json.loads(r['windows_json'])} for r in b.db.execute('SELECT * FROM clinician_availability WHERE org_id=?',(p.org_id,)) if r['clinician_id'] in allowed_staff]
        time_off=[dict(r) for r in b.db.execute('SELECT id,clinician_id,starts_at,ends_at FROM time_off WHERE org_id=? ORDER BY starts_at LIMIT 1000',(p.org_id,)) if r['clinician_id'] in allowed_staff]
        with b.db:b._audit(p,'workspace.read','workspace')
        return jsonify(user_id=p.user_id,role=role,timezone=b.organization_timezone(p),csrf=session['csrf'],cases=cases,clinicians=clinicians,assignments=assignments,availability=availability,time_off=time_off)
    @app.get('/api/appointments')
    def appointments():
        b=backend();zone=b.organization_timezone(g.principal)
        if request.args.get('from_date'):
            start=local_start(request.args['from_date'],'00:00',zone).isoformat()
            end_date=(date.fromisoformat(request.args.get('to_date',''))+timedelta(days=1)).isoformat()
            end=local_start(end_date,'00:00',zone).isoformat()
        else:start=request.args.get('from','');end=request.args.get('to','')
        return jsonify(items=b.list_appointments(g.principal,from_at=start,to_at=end,status=request.args.get('status') or None,limit=int(request.args.get('limit',100)),offset=int(request.args.get('offset',0))))
    def body(keys):
        value=request.get_json()
        if not isinstance(value,dict) or set(value)-set(keys):raise ValueError('Invalid request fields')
        integers={'version','duration','interval_weeks','count'}
        for name,item in value.items():
            if item is None:continue
            if name in integers and type(item) is not int:raise ValueError('Numeric fields must be whole numbers')
            if name=='windows' and not isinstance(item,list):raise ValueError('Working hours must be a list')
            if name not in integers|{'windows'} and not isinstance(item,str):raise ValueError('Text fields must be strings')
        return value
    @app.post('/api/appointments')
    def save():
        d=body(['id','version','case_id','clinician_id','title','date','time','duration','location','status'])
        b=backend();start=local_start(d.get('date',''),d.get('time',''),b.organization_timezone(g.principal)).isoformat()
        return jsonify(b.save_appointment(g.principal,d.get('case_id'),d.get('clinician_id'),d.get('title'),start,d.get('duration',60),d.get('location','Office'),d.get('status','Scheduled'),appointment_id=d.get('id'),expected_version=d.get('version')))
    @app.post('/api/series')
    def series():
        d=body(['case_id','clinician_id','title','date','time','duration','location','interval_weeks','count','request_key'])
        return jsonify(backend().create_series(g.principal,d.get('case_id'),d.get('clinician_id'),d.get('title'),d.get('date',''),d.get('time',''),d.get('duration',60),d.get('location','Office'),d.get('interval_weeks',1),d.get('count',2),d.get('request_key')))
    @app.post('/api/series/future')
    def future():
        d=body(['id','version','status','time','duration','location'])
        return jsonify(backend().update_series_future(g.principal,d.get('id'),d.get('version'),status=d.get('status'),clock=d.get('time'),duration=d.get('duration'),location=d.get('location')))
    @app.post('/api/availability')
    def availability():
        d=body(['clinician_id','windows']);backend().save_availability(g.principal,d.get('clinician_id'),d.get('windows'));return jsonify(ok=True)
    @app.post('/api/time-off')
    def time_off():
        d=body(['clinician_id','from_date','from_time','to_date','to_time']);b=backend();zone=b.organization_timezone(g.principal)
        return jsonify(id=b.add_time_off(g.principal,d.get('clinician_id'),local_start(d.get('from_date',''),d.get('from_time',''),zone).isoformat(),local_start(d.get('to_date',''),d.get('to_time',''),zone).isoformat()))
    @app.delete('/api/time-off/<tid>')
    def remove_time_off(tid):backend().remove_time_off(g.principal,tid);return jsonify(ok=True)
    return app
