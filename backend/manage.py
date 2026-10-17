"""Offline setup commands; no account self-enrolment through public endpoints."""
import argparse
import os
import secrets
from pathlib import Path
from dotenv import load_dotenv
import sqlite3
from core import Backend, Principal
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent.parent
load_dotenv(ROOT/'.env',override=False)
parser=argparse.ArgumentParser();parser.add_argument('command',choices=['init-local','seed-demo','map-identity','serve']);parser.add_argument('--issuer');parser.add_argument('--subject');parser.add_argument('--staff');parser.add_argument('--timezone',default='America/New_York');parser.add_argument('--port',type=int,default=8020)
args=parser.parse_args()
if args.command=='init-local':
    path=ROOT/'.env'
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'w') as file:
        file.write('EERO_SESSION_SECRET='+secrets.token_urlsafe(48)+'\nEERO_VAULT_KEY='+os.urandom(32).hex()+'\nEERO_DATABASE='+str(ROOT/'eero.db')+'\nEERO_PUBLIC_URL=http://127.0.0.1:8020\nEERO_LOCAL_HTTP=1\nEERO_OIDC_CLIENT_ID=\nEERO_OIDC_CLIENT_SECRET=\n')
    print('Local configuration created with private file permissions. Secrets were not printed. Next: seed-demo.')
elif args.command=='serve':
    from web import create_app
    create_app().run(host='127.0.0.1',port=args.port,debug=False)
else:
    db=sqlite3.connect(os.environ.get('EERO_DATABASE','eero.db'));b=Backend(db,bytes.fromhex(os.environ['EERO_VAULT_KEY']));p=Principal('eero','admin')
    if args.command=='seed-demo':
        ZoneInfo(args.timezone)
        with db:
            db.execute("INSERT OR IGNORE INTO organizations VALUES('eero','Eero fictional workspace')")
            for uid,role in [('admin','administrator'),('therapist-a','clinician'),('therapist-b','clinician')]:db.execute('INSERT OR IGNORE INTO staff(org_id,user_id,role) VALUES(?,?,?)',('eero',uid,role))
            db.execute('INSERT OR IGNORE INTO organization_settings VALUES(?,?)',('eero',args.timezone))
        if not db.execute("SELECT 1 FROM cases WHERE org_id='eero'").fetchone():
            cid=b.create_case(p,'Sample case 001')
            for uid in ('therapist-a','therapist-b'):b.assign(p,cid,uid)
        for uid in ('therapist-a','therapist-b'):
            if not db.execute('SELECT 1 FROM clinician_availability WHERE org_id=? AND clinician_id=?',('eero',uid)).fetchone():b.save_availability(p,uid,[{'day':day,'start':540,'end':1020} for day in range(5)])
        print('Fictional workspace initialized. Map verified provider subjects before staff can sign in.')
    else:
        if not args.issuer or not args.subject or not args.staff:parser.error('map-identity requires --issuer, --subject and --staff')
        with db:db.execute('INSERT INTO staff_identities VALUES(?,?,?,?)',(args.issuer,args.subject,'eero',args.staff))
        print('Staff identity mapped.')
    db.close()
