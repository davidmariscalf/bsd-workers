#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, http.server, importlib.util, json, os, queue, re, shutil, sqlite3, stat, subprocess, tarfile, tempfile, threading, time, uuid
from pathlib import Path

ROOT=Path(r'C:\bsd-mcp'); DB=ROOT/'bsd_lab_controller_v3.sqlite3'; CROOT=ROOT/'tool_candidates'; GATE=ROOT/'tool_promotion_retry_gate_v1.py'
GH=Path(r'C:\Program Files\GitHub CLI\gh.exe'); REPO='davidmariscalf/bsd-workers'; WF='candidate-private-test.yml'
IMG='sagemath/sagemath@sha256:e068670ae5863b54b2550e72437ec637b0283acb0dc712c8584c124dbf44e667'
GATE_SHA='61ea38387d9d6eda741a06ce3dd781b2ce08ec8a64486a008035361ebf64bb03'
VER='BSD_GITHUB_CANDIDATE_TEST_BRIDGE_V1'; RVER='BSD_GITHUB_CANDIDATE_TEST_RESULT_V1'
CID=re.compile(r'candidate_[a-f0-9]{16}\Z'); TUN=re.compile(r'https://[a-z0-9-]+\.trycloudflare\.com')
EXCLUDE={'promotion_retry_gate_v1.json','promotion_retry_gate_v1.tmp'}

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''): h.update(b)
    return h.hexdigest()

def cmd(a,timeout=60,check=True):
    r=subprocess.run(a,capture_output=True,text=True,timeout=timeout,shell=False)
    if check and r.returncode: raise RuntimeError(f'COMMAND_FAILED {r.returncode}: {a!r}\n{r.stdout}\n{r.stderr}')
    return r

def cf():
    p=shutil.which('cloudflared')
    if not p: raise RuntimeError('CLOUDFLARED_NOT_FOUND')
    return p

def preflight():
    if not GH.exists(): raise RuntimeError('GH_CLI_NOT_FOUND')
    if not GATE.exists() or sha(GATE)!=GATE_SHA: raise RuntimeError('PROMOTION_GATE_HASH_INVALID')
    if not DB.exists() or not CROOT.exists(): raise RuntimeError('LOCAL_STATE_MISSING')
    cmd([str(GH),'auth','status'],30)
    cmd([str(GH),'workflow','view',WF,'--repo',REPO],30)
    return {'gh':str(GH),'cloudflared':cf(),'gate_sha256':GATE_SHA,'image':IMG}

def con():
    c=sqlite3.connect(str(DB),timeout=30); c.row_factory=sqlite3.Row; return c

def row(cid):
    c=con()
    try:r=c.execute('SELECT candidate_id,status,path FROM tool_candidates WHERE candidate_id=?',(cid,)).fetchone()
    finally:c.close()
    if not r: raise RuntimeError('CANDIDATE_NOT_FOUND')
    return r

def workspace(cid):
    if not CID.fullmatch(cid): raise RuntimeError('INVALID_CANDIDATE_ID')
    r=row(cid)
    if r['status'] not in ('READY_FOR_TEST','TEST_FAILED'): raise RuntimeError(f"CANDIDATE_NOT_TESTABLE {r['status']}")
    root=CROOT.resolve(strict=True); w=(CROOT/cid).resolve(strict=True)
    if root not in w.parents: raise RuntimeError('CANDIDATE_PATH_ESCAPE')
    if r['path'] and Path(r['path']).resolve(strict=True)!=w: raise RuntimeError('CANDIDATE_DB_PATH_MISMATCH')
    return w

def reparse(p):
    s=p.lstat(); return bool(getattr(s,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400))

def files(w):
    out=[]; total=0
    for p in sorted(w.rglob('*')):
        if p.name in EXCLUDE: continue
        if p.is_symlink() or reparse(p): raise RuntimeError(f'REPARSE_BLOCKED {p}')
        if p.is_dir(): continue
        if not p.is_file(): raise RuntimeError(f'NON_REGULAR_FILE {p}')
        z=p.stat().st_size
        if z>8*1024*1024: raise RuntimeError(f'FILE_TOO_LARGE {p}')
        total+=z
        if total>32*1024*1024 or len(out)>=256: raise RuntimeError('CANDIDATE_TOO_LARGE')
        out.append(p)
    if not any(p.relative_to(w).as_posix().startswith('tests/test_') and p.suffix=='.py' for p in out): raise RuntimeError('NO_TESTS')
    return out

def fingerprint(w,fs):
    s='\n'.join(f'{p.relative_to(w).as_posix()}:{sha(p)}' for p in fs)
    return hashlib.sha256(s.encode()).hexdigest()

def archive(w,fs,dst):
    with tarfile.open(dst,'w:gz') as t:
        for p in fs:t.add(p,arcname=p.relative_to(w).as_posix(),recursive=False)
    return sha(dst)

class H(http.server.BaseHTTPRequestHandler):
    payload=None; route=''; served=None
    def do_GET(self):
        if self.path!=self.route:self.send_error(404);return
        if self.served.is_set():self.send_error(410);return
        z=self.payload.stat().st_size; self.send_response(200); self.send_header('Content-Type','application/gzip'); self.send_header('Content-Length',str(z)); self.send_header('Cache-Control','no-store'); self.end_headers()
        with self.payload.open('rb') as f:shutil.copyfileobj(f,self.wfile)
        self.served.set()
    def log_message(self,*a):pass

def serve(payload,secret):
    ev=threading.Event(); route=f'/payload/{secret}.tar.gz'; K=type('K',(H,),{'payload':payload,'route':route,'served':ev})
    s=http.server.ThreadingHTTPServer(('127.0.0.1',0),K); s.daemon_threads=True; th=threading.Thread(target=s.serve_forever,daemon=True); th.start(); return s,th,ev,s.server_address[1],route

def tunnel(port):
    p=subprocess.Popen([cf(),'tunnel','--url',f'http://127.0.0.1:{port}','--no-autoupdate'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1,shell=False)
    q=queue.Queue()
    def rd(st):
        if st:
            for line in iter(st.readline,''):q.put(line)
    threading.Thread(target=rd,args=(p.stdout,),daemon=True).start(); threading.Thread(target=rd,args=(p.stderr,),daemon=True).start()
    end=time.time()+45; seen=[]
    while time.time()<end and p.poll() is None:
        try:line=q.get(timeout=.5)
        except queue.Empty:continue
        seen.append(line.rstrip()); m=TUN.search(line)
        if m:return p,m.group(0)
    stop(p); raise RuntimeError('TUNNEL_URL_NOT_FOUND\n'+'\n'.join(seen[-20:]))

def stop(p):
    if p and p.poll() is None:
        try:p.terminate(); p.wait(10)
        except Exception:
            try:p.kill()
            except Exception:pass

def dispatch(cid,token,url,psha):
    cmd([str(GH),'workflow','run',WF,'--repo',REPO,'--ref','main','-f',f'candidate_id={cid}','-f',f'run_token={token}','-f',f'payload_url={url}','-f',f'payload_sha256={psha}','-f',f'image_ref={IMG}'],60)

def runid(cid,token):
    title=f'candidate-{cid}-{token}'; end=time.time()+90
    while time.time()<end:
        r=cmd([str(GH),'run','list','--repo',REPO,'--workflow',WF,'--event','workflow_dispatch','--limit','30','--json','databaseId,displayTitle,status,conclusion'],30)
        for x in json.loads(r.stdout or '[]'):
            if x.get('displayTitle')==title:return int(x['databaseId'])
        time.sleep(2)
    raise RuntimeError('GITHUB_RUN_NOT_FOUND')

def wait(rid):
    end=time.time()+1200
    while time.time()<end:
        x=json.loads(cmd([str(GH),'run','view',str(rid),'--repo',REPO,'--json','databaseId,status,conclusion,displayTitle,url'],30).stdout)
        if x.get('status')=='completed':return x
        time.sleep(5)
    raise RuntimeError('GITHUB_RUN_TIMEOUT')

def resultfile(rid,token,d):
    name=f'candidate-test-result-{token}'; d.mkdir(parents=True,exist_ok=True)
    r=cmd([str(GH),'run','download',str(rid),'--repo',REPO,'--name',name,'--dir',str(d)],120,False)
    if r.returncode: raise RuntimeError(f'ARTIFACT_DOWNLOAD_FAILED\n{r.stdout}\n{r.stderr}')
    xs=list(d.rglob('result.json'))
    if len(xs)!=1: raise RuntimeError('RESULT_JSON_NOT_UNIQUE')
    return xs[0]

def counts(s):
    d={'passed':0,'failed':0,'skipped':0,'errors':0}
    for n,k in re.findall(r'(\d+)\s+(passed|failed|skipped|errors?)\b',s or '',re.I):d['errors' if k.lower().startswith('error') else k.lower()]=max(d['errors' if k.lower().startswith('error') else k.lower()],int(n))
    return d

def validate(x,cid,token,rid,fp):
    checks=[(x.get('version')==RVER,'VERSION'),(x.get('candidate_id')==cid,'CID'),(x.get('run_token')==token,'TOKEN'),(str(x.get('github_run_id'))==str(rid),'RUN_ID'),(x.get('provider')=='github_actions','PROVIDER'),(x.get('image_ref')==IMG,'IMAGE')]
    for ok,name in checks:
        if not ok:raise RuntimeError('RESULT_'+name+'_MISMATCH')
    for k in ('network_disabled','rootfs_readonly','candidate_mount_readonly','non_root'):
        if x.get(k) is not True:raise RuntimeError('ISOLATION_'+k+'_FAILED')
    if x.get('production_active') is not False or x.get('automatically_promoted') is not False or x.get('mathematical_certification') is not False:raise RuntimeError('RESULT_SAFETY_FLAGS_INVALID')
    cl=x.get('classification')
    if cl not in ('PASS','QUALITY_FAILURE','INFRA_FAILURE'):raise RuntimeError('BAD_CLASSIFICATION')
    if cl=='PASS' and not (x.get('status')=='TEST_PASSED' and x.get('exit_code')==0 and x.get('technical_failure') is False):raise RuntimeError('BAD_PASS_RESULT')
    if cl=='QUALITY_FAILURE' and not (x.get('status')=='TEST_FAILED' and x.get('technical_failure') is False):raise RuntimeError('BAD_QUALITY_RESULT')
    if cl=='INFRA_FAILURE' and not (x.get('status')=='INFRA_FAILURE' and x.get('technical_failure') is True):raise RuntimeError('BAD_INFRA_RESULT')
    y=dict(x); y.update(counts(str(x.get('stdout') or ''))); y.update({'candidate_fingerprint':fp,'bridge_version':VER,'tests_passed':cl=='PASS'}); return y

def gate_module():
    s=importlib.util.spec_from_file_location('promotion_retry_gate_v1',GATE); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m

def last(cid):
    c=con()
    try:
        try:return c.execute('SELECT classification,candidate_fingerprint FROM tool_promotion_retry_attempt_v1 WHERE candidate_id=? ORDER BY id DESC LIMIT 1',(cid,)).fetchone()
        except sqlite3.OperationalError:return None
    finally:c.close()

def require_repair(cid,fp):
    p=last(cid)
    if p and p['classification']=='QUALITY_FAILURE' and p['candidate_fingerprint']==fp:raise RuntimeError('REPAIR_REQUIRED_SAME_FINGERPRINT')

def setstate(cid,res,st):
    cl=res['classification']
    if cl=='PASS':ns='TEST_PASSED'; note='GitHub isolated test passed; production inactive.'
    elif st['state']=='QUARANTINED':ns='QUARANTINED'; note='Three quality failures; activation blocked.'
    elif cl=='QUALITY_FAILURE':ns='TEST_FAILED'; note='Isolated quality failure; repair required before retry.'
    else:ns=None; note='GitHub infrastructure failure; quality attempt not consumed.'
    c=con()
    try:
        c.execute('BEGIN IMMEDIATE'); cur=c.execute('SELECT status FROM tool_candidates WHERE candidate_id=?',(cid,)).fetchone()
        if not cur or cur['status'] not in ('READY_FOR_TEST','TEST_FAILED'):raise RuntimeError('CANDIDATE_STATE_CHANGED')
        if ns:c.execute('UPDATE tool_candidates SET status=?,test_summary_json=?,notes=?,updated_at=datetime(\'now\') WHERE candidate_id=?',(ns,json.dumps(res,sort_keys=True),note,cid))
        else:c.execute('UPDATE tool_candidates SET notes=?,updated_at=datetime(\'now\') WHERE candidate_id=?',(note,cid))
        c.commit()
    except Exception:c.rollback();raise
    finally:c.close()

def once(cid):
    preflight(); w=workspace(cid); fs=files(w); fp=fingerprint(w,fs); require_repair(cid,fp)
    g=gate_module(); g.init_schema(); g.ensure_gate(cid); old=g.gate_row(cid)
    if old['state'] in ('QUARANTINED','BLOCKED_INFRA','TEST_PASSED'):raise RuntimeError('GATE_NOT_RUNNABLE_'+old['state'])
    token=uuid.uuid4().hex[:20]; secret=uuid.uuid4().hex+uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix='bsd-gh-candidate-') as td:
        d=Path(td); a=d/'candidate.tar.gz'; psha=archive(w,fs,a); srv=th=tun=None
        try:
            srv,th,served,port,route=serve(a,secret); tun,base=tunnel(port); dispatch(cid,token,base+route,psha); rid=runid(cid,token); meta=wait(rid); rf=resultfile(rid,token,d/'artifact'); res=validate(json.loads(rf.read_text(encoding='utf-8')),cid,token,rid,fp); res['github_conclusion']=meta.get('conclusion'); res['github_url']=meta.get('url')
            if fingerprint(w,files(w))!=fp:raise RuntimeError('CANDIDATE_CHANGED_DURING_REMOTE_TEST')
            st=g.persist_attempt(cid,res['classification'],res,fp); cert=g.write_certificate(cid,st,fp); setstate(cid,res,st)
            print(json.dumps({'status':'ok','candidate_id':cid,'classification':res['classification'],'quality_failures':st['quality_failures'],'infra_failures':st['infra_failures'],'gate_state':st['state'],'github_run_id':rid,'github_url':res.get('github_url'),'certificate':str(cert),'production_active':False,'automatically_promoted':False,'mathematical_certification':False},indent=2,sort_keys=True))
            return 0 if res['classification']=='PASS' else (31 if st['state']=='QUARANTINED' else 32 if st['state']=='BLOCKED_INFRA' else 10 if res['classification']=='QUALITY_FAILURE' else 20)
        finally:
            stop(tun)
            if srv:srv.shutdown();srv.server_close()
            if th:th.join(5)

def status(cid=None):
    c=con()
    try:
        if cid:rs=c.execute('SELECT candidate_id,status,notes,updated_at FROM tool_candidates WHERE candidate_id=?',(cid,)).fetchall()
        else:rs=c.execute("SELECT candidate_id,status,notes,updated_at FROM tool_candidates WHERE status IN ('READY_FOR_TEST','TEST_FAILED','QUARANTINED','TEST_PASSED') ORDER BY updated_at DESC LIMIT 50").fetchall()
    finally:c.close()
    print(json.dumps([dict(x) for x in rs],indent=2,default=str));return 0

def selftest():
    e=preflight(); print(json.dumps({'version':VER,'selftest':'PASS',**e,'candidate_executed':False,'production_changed':False,'f776_touched':False},indent=2,sort_keys=True));return 0

def main():
    p=argparse.ArgumentParser();p.add_argument('--candidate');p.add_argument('--status',action='store_true');p.add_argument('--selftest',action='store_true');a=p.parse_args()
    if a.selftest:return selftest()
    if a.status:return status(a.candidate)
    if not a.candidate:p.error('--candidate required')
    return once(a.candidate)

if __name__=='__main__':raise SystemExit(main())
