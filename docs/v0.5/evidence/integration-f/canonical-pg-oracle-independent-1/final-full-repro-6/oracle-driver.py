import json,sys,os,hashlib
from pathlib import Path
import canonical_coverage_audit as pinned_oracle
assert hashlib.sha256(Path(pinned_oracle.__file__).read_bytes()).hexdigest()==os.environ['F_CANONICAL_EXPECTED_ORACLE_SHA256']
from real_golden_audit import canonical_coverage_from_sql
data=json.loads(Path(sys.argv[1]).read_text())
try:
 coverage=canonical_coverage_from_sql(data,data['narrations'][0],data['turns'],data['commits'])
 target=data['narrations'][0]['plan_json']['_cnyPriceCoveragePolicy']['targets'][0]['segmentId']
 turn=data['turns'][0]['turn_id']
 if coverage != {target:[turn]}: raise ValueError('unexpected coverage map')
 print(json.dumps({'status':'PASS','coverageTargets':len(coverage),'scope':'controlled PG policy/sink fixture, not physical playback'}))
except Exception as error:
 print(json.dumps({'status':'FAIL','errorType':type(error).__name__,'code':getattr(error,'code','ORACLE_FAILED')}))
 sys.exit(1)
