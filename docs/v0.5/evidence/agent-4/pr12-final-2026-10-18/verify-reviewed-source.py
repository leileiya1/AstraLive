import pathlib,subprocess,json,hashlib,argparse
ap=argparse.ArgumentParser();ap.add_argument('--source',required=True);ap.add_argument('--output',required=True);a=ap.parse_args()
s=pathlib.Path(a.source);repo=pathlib.Path('/Users/sapiece/innovationProject/AstraLive-agent-4'); frozen='c7fd46209d3cbc6f58541dba8b4e1c85609c823e';base='235258ad75f7d271a279ea89fd88ddf80e797f31';pr='c0f36e1bf1f060286eedd733cd222cfa6c7941f3';digest='3c0c317ed00f6fa4d2cf15ef3f61fc002d4bb22bf02d53ee9f1b407458bb28b1'
def git(*args):return subprocess.check_output(['git','-C',str(repo),*args])
def sha(x):return hashlib.sha256(x).hexdigest()
mfile='contracts/v0.5/durable-live-2/manifest.json';m=json.loads((s/mfile).read_bytes()); hashes={p:sha((s/p).read_bytes()) for p in m['files']};actual=sha(json.dumps(hashes,sort_keys=True,separators=(',',':')).encode());assert len(hashes)==22 and hashes==m['files'] and actual==digest
assert (s/mfile).read_bytes()==git('show',f'{frozen}:{mfile}')
assert all((s/p).read_bytes()==git('show',f'{frozen}:{p}') for p in hashes)
paths=git('diff','--name-only',base,pr).decode().splitlines();assert all(p.startswith(('backend/internal/contentplan/answerstream/','backend/internal/turnmanager/answerstream/','docs/v0.5/implementation/')) or p=='docs/v0.5/AGENT-3-HANDOFF.md' for p in paths)
assert all((s/p).read_bytes()==git('show',f'{pr}:{p}') for p in paths)
protected=json.loads((s/'contracts/v0.5/durable-live-2/protected-files.json').read_text());print('protected shape',list(protected)[:5])
# Compare all tracked paths outside Agent3 additions with the reviewed integration.
basepaths=git('ls-tree','-r','--name-only',base).decode().splitlines();same=[]
for p in basepaths:
 if p in paths:continue
 assert (s/p).read_bytes()==git('show',f'{base}:{p}'),p
 same.append(p)
migrations=sorted(p.name for p in (s/'backend/db/migrations').glob('*.sql'));assert len(migrations)==7 and [x[:6] for x in migrations]==[f'{i:06}' for i in range(1,8)]
assert b'OUTPUT_FENCE_UNPROVEN' in (s/'runtime/app/main.py').read_bytes()
assert b'CheckLiveAdmission' in (s/'backend/cmd/server/main.go').read_bytes()
result=dict(prHead=pr,integrationBase=base,frozenCommit=frozen,normativeDigest=actual,normativeFiles=hashes,manifestSHA256=sha((s/mfile).read_bytes()),allNormativeBytesEqualFrozen=True,changedPaths=paths,unchangedBaseFileCount=len(same),migrations=migrations,sourceHashes={p:sha((s/p).read_bytes()) for p in paths if not p.startswith('docs/')},authorityTree=git('rev-parse',f'{pr}:backend/internal/durablelivev2/authority').decode().strip(),officialDTOGoTree=git('rev-parse',f'{pr}:backend/internal/durablelivev2/wire').decode().strip(),officialDTOPythonTree=git('rev-parse',f'{pr}:astralive_contracts/durable_live_v2').decode().strip(),productionEntrypointsUnchanged=True,freezeAndOwnership='PASS')
pathlib.Path(a.output).write_text(json.dumps(result,indent=2)+'\n');print('PASS',len(hashes),actual,len(same),migrations)
