import gzip,hashlib,json,sys,tarfile
from pathlib import Path,PurePosixPath
from gpu_worker.config import Config
from gpu_worker.install import verify_bundle
bundle=Path(sys.argv[1]);cfg=Config.load(sys.argv[2]);verified=verify_bundle(bundle)
lab=Path(cfg.lab_root);manifest=json.loads((lab/'reports/soulx-weight-manifest.json').read_text())
expected={}
for row in manifest:
 repo='wav2vec2-base-960h' if row['repo'].startswith('facebook/') else 'SoulX-FlashHead-1_3B'
 expected['models/soulx/'+repo+'/'+row['file']]=row['sha256']
expected['reports/soulx-weight-manifest.json']=cfg.manifest_sha256
expected[str(Path(cfg.asset_path).relative_to(lab))]=cfg.asset_sha256
seen=set();files=raw=0
with gzip.open(bundle/'lab-payload.tar.gz','rb') as stream:
 with tarfile.open(fileobj=stream,mode='r|') as archive:
  for member in archive:
   p=PurePosixPath(member.name)
   assert member.isfile() and not p.is_absolute() and '..' not in p.parts
   assert '.private' not in p.parts
   assert member.name in expected or member.name.startswith(('environments/astralive-soulx/','repositories/SoulX-FlashHead/','streaming/worker-deps/'))
   assert member.name not in seen
   seen.add(member.name);files+=1;raw+=member.size
   if member.name in expected:
    assert hashlib.file_digest(archive.extractfile(member),'sha256').hexdigest()==expected[member.name]
   elif member.name.startswith('models/'):
    raise AssertionError('UNEXPECTED_MODEL_ASSET')
 while stream.read(1024*1024): pass
assert expected.keys() <= seen
result={'verdict':'PASS_BUNDLE_CONTENT_AND_PINNED_ASSETS','bundleReleaseId':verified,'payloadBytes':(bundle/'lab-payload.tar.gz').stat().st_size,'regularFiles':files,'uncompressedBytes':raw,'pinnedWeightFilesVerified':len(manifest),'pinnedAssetsVerified':len(expected),'freshHostRestoreVerified':False,'baseImageRequired':True}
print(json.dumps(result))
(lab/'reports/rtx3080-offline-bundle.json').write_text(json.dumps(result,indent=2)+'\n')
