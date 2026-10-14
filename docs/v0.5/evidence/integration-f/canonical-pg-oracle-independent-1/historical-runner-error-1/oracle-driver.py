import json,sys
from pathlib import Path
from real_golden_audit import canonical_coverage_from_sql
data=json.loads(Path(sys.argv[1]).read_text())
try:
 coverage=canonical_coverage_from_sql(data)
 target=data['narrations'][0]['plan_json']['_cnyPriceCoveragePolicy']['targets'][0]['segmentId']
 turn=data['turns'][0]['turn_id']
 if coverage != {target:[turn]}: raise ValueError('unexpected coverage map')
 print(json.dumps({'status':'PASS','coverageTargets':len(coverage),'scope':'controlled PG policy/sink fixture, not physical playback'}))
except Exception as error:
 print(json.dumps({'status':'FAIL','errorType':type(error).__name__,'code':getattr(error,'code','ORACLE_FAILED')}))
 sys.exit(1)
