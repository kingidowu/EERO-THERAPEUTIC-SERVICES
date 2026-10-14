import hashlib,json,sqlite3,tempfile,time,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs,urlparse
import requests
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from joserfc import jwt
from joserfc.jwk import RSAKey
from core import Backend,Principal
from web import create_app
class WebTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=str(Path(self.tmp.name)/'sample.db');self.db=sqlite3.connect(self.path);self.b=Backend(self.db,b'k'*32)
  with self.db:
   self.db.execute("INSERT INTO organizations VALUES('eero','Sample')")
   self.db.executemany('INSERT INTO staff(org_id,user_id,role) VALUES(?,?,?)',[('eero','admin','administrator'),('eero','c','clinician'),('eero','outside','clinician')])
   self.db.execute("INSERT INTO staff_identities VALUES('https://accounts.google.com','known-subject','eero','admin')")
  self.p=Principal('eero','admin');self.cid=self.b.create_case(self.p,'Sample');self.b.assign(self.p,self.cid,'c')
  self.app=create_app({'TESTING':True,'DATABASE':self.path,'SECRET_KEY':'s'*48,'VAULT_KEY':b'k'*32,'SESSION_COOKIE_SECURE':False,'PUBLIC_URL':'http://localhost','OIDC_CLIENT_ID':'test-client','OIDC_CLIENT_SECRET':'test-secret'});self.client=self.app.test_client()
 def tearDown(self):self.db.close();self.tmp.cleanup()
 def authenticated(self,user='admin'):
  token='test-session-'+user
  with self.db:self.db.execute('INSERT OR REPLACE INTO web_sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),'eero',user,(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()))
  client=self.app.test_client()
  with client.session_transaction() as s:s['staff_session']=token;s['csrf']='test-csrf'
  return client
 def payload(self,**kw):
  d=dict(case_id=self.cid,clinician_id='c',title='Sample shared',date='2099-12-01',time='09:00',duration=60,location='Office',status='Scheduled');d.update(kw);return d
 def post(self,c,path,d):return c.post(path,json=d,headers={'X-CSRF-Token':'test-csrf','Origin':'http://localhost'})
 def test_anonymous_headers_and_forged_cookie(self):
  self.assertEqual(self.client.get('/api/bootstrap',headers={'X-User-ID':'admin','X-Role':'administrator'}).status_code,401)
  self.client.set_cookie('session','forged');self.assertEqual(self.client.get('/api/bootstrap').status_code,401)
 def test_csrf_origin_and_forged_principal(self):
  c=self.authenticated();self.assertEqual(c.post('/api/appointments',json=self.payload()).status_code,403)
  self.assertEqual(c.post('/api/appointments',json=self.payload(),headers={'X-CSRF-Token':'test-csrf','Origin':'https://evil.invalid'}).status_code,403)
  self.assertEqual(self.post(c,'/api/appointments',self.payload(org_id='other')).status_code,400)
 def test_two_staff_share_data_and_assignments_limit_access(self):
  a=self.authenticated();c=self.authenticated('c');outside=self.authenticated('outside');self.assertEqual(self.post(a,'/api/appointments',self.payload()).status_code,200)
  query='/api/appointments?from_date=2099-12-01&to_date=2099-12-01';self.assertEqual(len(c.get(query).json['items']),1);self.assertEqual(outside.get(query).json['items'],[])
  row=c.get(query).json['items'][0];self.assertEqual(self.post(c,'/api/appointments',self.payload(id=row['id'],version=row['version'],status='Completed')).status_code,200)
  self.assertEqual(self.post(a,'/api/appointments',self.payload(id=row['id'],version=row['version'],status='No-show')).status_code,400)
 def test_malformed_payloads_are_rejected(self):
  c=self.authenticated()
  for change in [{'case_id':{}},{'duration':True},{'title':[]},{'version':'1'}]:
   self.assertEqual(self.post(c,'/api/appointments',self.payload(**change)).status_code,400)
 def test_logout_revocation_and_expiry(self):
  c=self.authenticated();cookie=c.get_cookie('session').value;self.assertEqual(self.post(c,'/api/logout',{}).status_code,200)
  replay=self.app.test_client();replay.set_cookie('session',cookie);self.assertEqual(replay.get('/api/bootstrap').status_code,401)
  c=self.authenticated()
  with self.db:self.db.execute("UPDATE web_sessions SET expires_at='2000-01-01T00:00:00+00:00'")
  self.assertEqual(c.get('/api/bootstrap').status_code,401)
 def test_inactive_staff_revoked(self):
  c=self.authenticated()
  with self.db:self.db.execute("UPDATE staff SET active=0 WHERE user_id='admin'")
  self.assertEqual(c.get('/api/bootstrap').status_code,403)
 def test_security_headers(self):
  r=self.client.get('/');self.assertEqual(r.status_code,200);self.assertIn(b'Sign in with Google',r.data);r.close()
  r=self.authenticated().get('/api/bootstrap');self.assertEqual(r.headers['Cache-Control'],'no-store');self.assertEqual(r.headers['X-Frame-Options'],'DENY')
 def test_unconfigured_google_client_stays_unavailable(self):
  app=create_app({'TESTING':True,'DATABASE':self.path,'SECRET_KEY':'s'*48,'VAULT_KEY':b'k'*32,'PUBLIC_URL':'http://localhost','SESSION_COOKIE_SECURE':False,'OIDC_CLIENT_ID':None,'OIDC_CLIENT_SECRET':None})
  c=app.test_client();self.assertFalse(c.get('/auth/status').json['ready']);self.assertEqual(c.get('/auth/login').status_code,503);self.assertEqual(c.get('/api/bootstrap').status_code,401)
 def test_known_subject_required(self):
  remote=self.app.extensions['eero_oauth'].staff
  for issuer,subject,code in [('https://accounts.google.com','unknown',403),('https://wrong.invalid','known-subject',401)]:
   with patch.object(remote,'authorize_access_token',return_value={'userinfo':{'iss':issuer,'sub':subject}}):self.assertEqual(self.client.get('/auth/callback').status_code,code)
 def flow(self,change=None,tamper=False):
  key=rsa.generate_private_key(public_exponent=65537,key_size=2048);private=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption());public=RSAKey.import_key(key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo),{'kid':'fixture-key'}).as_dict(private=False)
  metadata={'issuer':'https://accounts.google.com','authorization_endpoint':'https://provider.invalid/auth','token_endpoint':'https://provider.invalid/token','jwks_uri':'https://provider.invalid/jwks','id_token_signing_alg_values_supported':['RS256']};claims={}
  def response(method,url,**kwargs):
   r=requests.Response();r.status_code=200;r.url=url
   if url.endswith('openid-configuration'):body=metadata
   elif url.endswith('/jwks'):body={'keys':[public]}
   elif url.endswith('/token'):
    token=jwt.encode({'alg':'RS256','kid':'fixture-key'},claims,RSAKey.import_key(private))
    if tamper:token=token[:-8]+'AAAAAAAA'
    body={'access_token':'synthetic-access','token_type':'Bearer','id_token':token}
   else:raise AssertionError('Unexpected provider call')
   r._content=json.dumps(body).encode();r.headers['Content-Type']='application/json';return r
  with patch('requests.sessions.Session.request',side_effect=response):
   login=self.client.get('/auth/login');q=parse_qs(urlparse(login.location).query);self.assertEqual(q['code_challenge_method'],['S256']);claims.update(iss='https://accounts.google.com',sub='known-subject',aud='test-client',exp=int(time.time())+300,iat=int(time.time()),nonce=q['nonce'][0])
   if change:claims.update(change)
   return self.client.get('/auth/callback?state='+q['state'][0]+'&code=fixture-code')
 def test_signed_oidc_flow(self):
  self.assertEqual(self.flow().status_code,302);self.assertEqual(self.client.get('/api/bootstrap').status_code,200)
 def test_invalid_oidc_tokens(self):
  for change in [{'iss':'https://wrong.invalid'},{'aud':'wrong'},{'nonce':'wrong'},{'exp':int(time.time())-3600}]:
   with self.subTest(change=change):
    self.client=self.app.test_client();self.assertEqual(self.flow(change).status_code,401);self.assertEqual(self.client.get('/api/bootstrap').status_code,401)
  self.client=self.app.test_client();self.assertEqual(self.flow(tamper=True).status_code,401)
 def test_missing_login_state(self):self.assertEqual(self.client.get('/auth/callback?state=fake&code=fixture').status_code,401)
