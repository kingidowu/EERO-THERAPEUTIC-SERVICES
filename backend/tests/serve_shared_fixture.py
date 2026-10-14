"""Loopback-only browser fixture. Synthetic provider responses exist ONLY in this test file."""
import logging,os,secrets,sqlite3,sys,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from flask import redirect,request
from core import Backend,Principal
from web import create_app
logging.getLogger('werkzeug').setLevel(logging.ERROR)
port=int(sys.argv[1])
with tempfile.TemporaryDirectory() as folder:
 path=str(Path(folder)/'fixture.db');db=sqlite3.connect(path);b=Backend(db,b'k'*32)
 with db:
  db.execute("INSERT INTO organizations VALUES('eero','Fictional browser fixture')")
  db.executemany('INSERT INTO staff(org_id,user_id,role) VALUES(?,?,?)',[('eero','admin','administrator'),('eero','therapist-a','clinician')])
  db.executemany('INSERT INTO staff_identities VALUES(?,?,?,?)',[('https://accounts.google.com','fixture-admin','eero','admin'),('https://accounts.google.com','fixture-therapist','eero','therapist-a')])
 p=Principal('eero','admin');cid=b.create_case(p,'Shared sample case');b.assign(p,cid,'therapist-a');b.save_availability(p,'therapist-a',[{'day':day,'start':540,'end':1020} for day in range(5)]);db.close()
 app=create_app({'TESTING':True,'DATABASE':path,'SECRET_KEY':secrets.token_urlsafe(48),'VAULT_KEY':b'k'*32,'SESSION_COOKIE_SECURE':False,'PUBLIC_URL':f'http://127.0.0.1:{port}','OIDC_CLIENT_ID':'fixture-client','OIDC_CLIENT_SECRET':'fixture-secret'})
 remote=app.extensions['eero_oauth'].staff;next_login=[0]
 def synthetic_redirect(*args,**kwargs):
  next_login[0]+=1;subject='fixture-admin' if next_login[0]%2 else 'fixture-therapist'
  return redirect('/auth/callback?fixture_subject='+subject)
 def synthetic_token():return {'userinfo':{'iss':'https://accounts.google.com','sub':request.args['fixture_subject']}}
 with patch.object(remote,'authorize_redirect',side_effect=synthetic_redirect),patch.object(remote,'authorize_access_token',side_effect=synthetic_token):
  app.run(host='127.0.0.1',port=port,debug=False)
